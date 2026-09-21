# Session / Security Audit

Unlike every prior audit in this project, the subject here is **this
repo's own implementation** (built across the authentication, users,
teams, RBAC and permissions phases), evaluated against
[`../modules/session_security.md`](../modules/session_security.md).
`jdk_clean` has nothing to contribute: a repo-wide search for CSRF
handling, security headers, or cookie-session code returns zero matches
— it never built any of this either, so there's no legacy pattern to
audit for reuse or rejection.

## The one real decision: cookie session vs. bearer token

§2 conditionally prefers "server-managed session + secure HttpOnly
cookie... rather than storing authentication tokens in `localStorage`."
This project keeps the bearer-token design from
[`AUTHENTICATION_AUDIT.md`](AUTHENTICATION_AUDIT.md) instead. Reasoning:

1. **The specific problem named doesn't exist here.** §2's concern is
   tokens sitting in `localStorage`, readable by any injected script. No
   frontend exists yet in `jdk_erp` — there is no `localStorage` call to
   have gotten wrong. The access token is already never persisted
   anywhere (in-memory only, by design, since the authentication phase).
2. **A bearer token is immune to CSRF by construction** — a browser
   never automatically attaches an `Authorization` header to a
   cross-site request the way it does a cookie. Switching to
   cookie-based auth would *introduce* the CSRF risk §9 then asks to be
   defended against. Staying with bearer tokens makes §9 not-applicable
   rather than something to build — fewer moving parts, which is this
   whole document's stated goal ("keep the implementation small").
3. **Cost/benefit of switching now.** Doing so would mean rewriting
   `auth_service`, `api/deps.get_current_user`, every existing endpoint's
   auth dependency, and re-verifying all 78 existing tests, for a
   transport decision with no concrete frontend yet to validate it
   against. §2's own framing is conditional ("if JDK is a browser-based
   ERP") — best evaluated once a real frontend makes that trade-off
   concrete, not guessed at now.
4. **Mobile compatibility stays open.** `jdk_clean` shipped a
   React Native app (`mobile-app-rn`) alongside its web frontend. Bearer
   tokens work identically for both; cookies are awkward for a mobile
   API client. Nothing in this project's roadmap has ruled out a mobile
   client, so keeping the transport mobile-friendly by default costs
   nothing and forecloses nothing.

This is revisited if/when a real frontend is built and its author judges
cookies genuinely better for that concrete client — not decided
speculatively here.

## Section-by-section

| § | Requirement | Status |
| - | ----------- | ------ |
| 1 | Server-authorized, not frontend-decided | ✅ Already true — every endpoint depends on `get_current_user`/`require_admin`, never trusts a client-supplied identity field. |
| 2 | Secure session model | ⚠️ Bearer token kept, not cookie — see above. Token never in `localStorage` (nothing to fix, no frontend exists). |
| 3 | Login flow incl. organisation/user status checks | ✅ `auth_service.login` already checks both, in this order, before issuing anything (`AUTHENTICATION_AUDIT.md`, `ORGANISATION_AUDIT.md`). |
| 4 | Never trust client-supplied identity | ✅ `organisation_id`/`role`/`team_id` are always read from the database via the authenticated user row, never accepted as request fields. |
| 5 | Idle + absolute timeout | ⚠️ Only absolute timeout existed (`REFRESH_TOKEN_EXPIRE_DAYS`). **Gap — closed this phase**: idle timeout added, checked at the same point the refresh token already gets a database write, so it adds no cost to ordinary requests (§16). |
| 6 | Logout invalidates session | ✅ Already true — `auth_service.logout` revokes the specific refresh token server-side (`AUTHENTICATION_AUDIT.md` §5). |
| 7 | Password change/reset invalidates sessions | ✅ Already true — `change_password` revokes every refresh token for the user. |
| 8 | Role/team changes take effect immediately; invalidate sessions for sensitive ones | ✅ Immediate effect already guaranteed by construction — role is never cached in a token (`RBAC_AUDIT.md` #7), so every check re-reads it. **Gap — closed this phase**: role changes now also revoke sessions as the "additional safeguard" §8 asks for. Plain team-membership add/remove does not force logout — it's not the "particularly sensitive" case §8's own example (a role demotion) describes, and immediate effect is already guaranteed either way. |
| 9 | CSRF protection | N/A — no cookie-based auth exists to protect (see decision above). |
| 10 | Brute-force protection, no enumeration | ✅ Already true — rolling-window lockout by username, and unknown-user/wrong-password/inactive-account/locked-out all resolve to one generic message where required (`AUTHENTICATION_AUDIT.md` §3-4). |
| 11 | Security headers, centralized | ❌ Gap — closed this phase: a single middleware in `app/main.py` sets them on every response. |
| 12 | Input/output security | ✅ Already true — every query is ORM-parameterized (`AUTHENTICATION_AUDIT.md` §10), `UserOut` never includes `password_hash`. |
| 13 | Sensitive data never logged | ✅ Already true by omission — this project has no request-body logging at all (unlike `jdk_clean`'s `request_logging.py`, which had to explicitly avoid logging bodies to not capture passwords; this project simply never built body logging in the first place), and `AuthEvent` never stores a password or token. |
| 14 | Audit security events | ⚠️ Login/logout/password-change already covered. **Gap — closed this phase**: `role_changed`, `team_added`, `team_removed` added to `AuthEventType`, each now recording the acting admin (`actor_user_id`), not just the affected user. |
| 15 | Recovery kept simple | ✅ Admin-reset-only is the plan; self-service reset isn't built, matching "don't build it speculatively." (Admin-initiated reset itself isn't built yet either — it's still tracked as part of the deferred user-management admin API, per `USERS_AUDIT.md`.) |
| 16 | Performance | ✅ Idle-timeout check added at the existing refresh-rotation write, not as a new per-request query; access-token validation stays a stateless JWT decode with one user lookup, unchanged. |

## HTTPS enforcement (acceptance criterion 14)

Not something the application can guarantee on its own in every
deployment shape (a TLS-terminating load balancer in front of it is
equally valid and common), so this phase adds an opt-in
`FORCE_HTTPS` setting: when enabled, plain HTTP requests are redirected
to HTTPS. Left off by default (`False`) so local development over plain
HTTP keeps working without extra configuration; documented in
`.env.example` for production deployments that terminate TLS at the app
itself rather than upstream.
