# JDK Session / Security

Hardening layer across everything built in
[`authentication.md`](authentication.md) through
[`permissions.md`](permissions.md), per [`../ROADMAP.md`](../ROADMAP.md).
Strong but deliberately boring: a few well-implemented fundamentals, not
a security framework.

## 1. Principle

Authenticate once, establish a secure session, and make every protected
request server-authorized. Don't put security decisions in the frontend.

## 2. Session model

If JDK is a browser-based ERP, prefer a server-managed session + secure
HttpOnly cookie over storing authentication tokens in `localStorage`.
Production cookies should be `HttpOnly`, `Secure`, an appropriate
`SameSite`, and narrowly scoped. HTTPS is mandatory in production.

> See this document's implementation-approach section for why this
> project keeps the bearer-token transport built in the authentication
> phase rather than switching to a cookie here.

## 3. Login

```text
Login → Validate credentials → Check organisation status → Check user
status → Create new session → Record login → ERP
```

On success: create a fresh session, never reuse a pre-login identifier,
store only the minimum server-side session information required.

## 4. Every protected request

```text
Current User → Organisation → Role → Teams → Authorization
```

Never trust `user_id`, `organisation_id`, `role`, `team_id`, or
`permissions` from the browser — the server derives all of them from the
authenticated session/database on every request.

## 5. Session expiration

Use both an **idle timeout** (expire after inactivity) and an
**absolute timeout** (even an active session eventually re-authenticates).
Values are configuration, not hard-coded.

## 6. Logout

Invalidate the server-side session, expire the browser cookie (if used),
and prevent reuse of the previous session. If multiple active sessions
are supported, logout invalidates at least the current one.

## 7. Password changes/resets

Changing or resetting a password invalidates the user's existing
sessions — particularly important for an admin-initiated reset.

## 8. Role/team changes

Security-sensitive changes take effect immediately — the next
authorization check must use the new state, never a stale cached one.
For particularly sensitive changes, also invalidate the user's existing
sessions as an additional safeguard.

## 9. CSRF protection

If JDK uses cookie-based authentication, state-changing requests
(create, edit, delete, approve, payment, password changes, user/role/team
changes) need CSRF protection. GET requests must never perform
state-changing operations.

## 10. Brute-force protection

Rate limit login, throttle where appropriate, and never reveal whether a
username exists — "Invalid username or password," not "User does not
exist." No elaborate fraud-detection system.

## 11. Security headers

Content-Security-Policy, `X-Content-Type-Options`, `Referrer-Policy`,
frame protection, and HSTS in HTTPS production — configured centrally,
not scattered across modules.

## 12. Input and output security

Validate input, use parameterized queries, reject unexpected input,
enforce authorization before sensitive operations, and avoid returning
unnecessary sensitive data. Never construct SQL from raw user input.

## 13. Sensitive data

Never log passwords, password reset tokens, session IDs, authentication
cookies, or secrets. Logs should be useful for diagnosis without being a
security liability.

## 14. Audit security events

Record login success/failure, logout, password change/reset, account
activation/deactivation, role changes, and team-membership changes — at
minimum user, action, timestamp, and relevant context.

## 15. Recovery

Admin reset is sufficient for now if it matches the business model.
Self-service email recovery can be added later if genuinely required —
don't build it speculatively.

## 16. Performance

Security must not become a bottleneck: avoid querying every permission,
team, and role on every request. Reuse the authenticated user context,
index what's actually queried, cache only where genuinely useful.

## Security boundaries

```text
Browser → Authentication → Secure Session → Current User Context →
Authorization/RBAC → Business Rules → Database
```

Never: `Browser → "I am Admin" → Database`.

## Acceptance tests

1. Unauthenticated users cannot access protected pages/API.
2. Invalid credentials are rejected.
3. Inactive users cannot log in.
4. Session cookies are appropriately secured.
5. Session expires after configured limits.
6. Logout invalidates the session.
7. Password reset invalidates existing sessions.
8. Role/team changes cannot leave stale elevated access.
9. CSRF protection works on state-changing requests.
10. Repeated login attempts are rate-limited.
11. Direct API manipulation cannot bypass authentication or authorization.
12. Passwords, tokens and session secrets never appear in logs.
13. Security events are auditable.
14. HTTPS is enforced in production.

## The principle to lock in

> Use standard, proven web security mechanisms; centralize them; keep the
> implementation small; never invent our own cryptography, token system
> or security protocol.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16
and the roadmap's audit-first rule: see
[`../audit/SESSION_SECURITY_AUDIT.md`](../audit/SESSION_SECURITY_AUDIT.md),
which audits this project's *own* implementation (built across the
authentication through permissions phases) against every section above,
rather than `jdk_clean` — `jdk_clean` has no security headers, CSRF
handling, or cookie-session code at all to audit for reuse.

**The one deliberate deviation, stated plainly:** §2 conditionally
prefers a cookie-based session ("if JDK is a browser-based ERP"). This
project keeps the bearer-token design built in the authentication phase
instead, for reasons detailed in the audit doc — chiefly that no
frontend exists yet in this repo to have the `localStorage` problem §2
warns about, that a bearer token is immune to CSRF by construction
(making §9 not-applicable rather than something to build), and that
switching now would mean rewriting and re-verifying the entire tested
authentication core for a transport decision with no concrete consumer
yet to validate it against. Every other section is implemented against
the existing design.

**What's implemented in this phase**, on top of what authentication
already had:

- Idle timeout (`SESSION_IDLE_TIMEOUT_MINUTES`) on top of the existing
  absolute timeout (`REFRESH_TOKEN_EXPIRE_DAYS`) — checked and slid
  forward at the same point the refresh token is already rotated, so it
  costs no extra query on ordinary API requests (§16).
- Role changes now also revoke the user's sessions (§8's "additional
  safeguard"), on top of the correctness guarantee that already existed
  (no role/permission data is ever cached in a token — every check reads
  the database fresh, so a stale token can't carry stale authority even
  without this).
- `auth_events` gains `role_changed`, `team_added`, and `team_removed`,
  each recording who performed the action, not just who it affected
  (§14).
- Centralized security headers middleware (§11) and configurable HTTPS
  enforcement (§14 acceptance criterion) for production.

**Already satisfied by the authentication phase, not rebuilt here**:
login rate limiting, generic invalid-credential messaging, parameterized
queries throughout, no sensitive data in logs, password change already
revoking all sessions. See
[`../audit/SESSION_SECURITY_AUDIT.md`](../audit/SESSION_SECURITY_AUDIT.md)
for the full point-by-point mapping.
