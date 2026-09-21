# JDK Authentication — Definition

Phase 1 of [`ROADMAP.md`](../ROADMAP.md) starts with the foundation, and
the foundation starts with authentication — built alone, first, as a clean
identity layer. RBAC, teams and departmental access are a separate,
later layer that consumes this one. This document is the spec that layer
is built and audited against.

## 1. Purpose

Authentication answers only:

> Who is this user, and are they allowed to establish a session?

It does not decide what the user can see or do. That belongs to
RBAC/authorization — a different module, built on top of this one, never
inside it.

## 2. User identity

Each user has:

- Unique user ID
- Name
- Email/username used for login
- Secure password hash
- Active/inactive status
- Organisation ID
- Created/updated timestamps
- Last login timestamp

Avoid storing duplicate identity information in different user tables —
one users table, one identity.

## 3. Login

Simple:

```
Login → Validate credentials → Create secure session → Application
```

Requirements:

- Username/email + password
- Clear invalid-credential response
- Inactive user cannot log in
- Secure session/token handling
- Session expiry
- Logout
- No sensitive information in responses/logs

Don't add OTP, SSO, social login, MFA, etc. unless the business actually
needs them.

## 4. Password

Password policy:

- Minimum 8 characters
- At least 1 uppercase
- At least 1 number
- At least 1 special character

Passwords must be:

- Hashed using a modern password-hashing algorithm
- Never stored or logged in plaintext
- Never returned through an API

Support:

```
Set password → Change password → Admin reset
```

Password reset should invalidate existing sessions where practical.

## 5. Session security

Keep this simple and robust:

- Secure session mechanism appropriate to the existing stack
- HttpOnly cookies if using cookie-based authentication
- Secure flag in HTTPS production
- Appropriate SameSite policy
- Session expiration
- Logout invalidates the session
- Inactive users are rejected even if they previously had a valid session

## 6. Authentication vs authorization

This boundary is important:

```text
Authentication
    ↓
Who are you?
    ↓
Authenticated User
    ↓
Authorization / RBAC
    ↓
What can you access?
    ↓
Business Module
```

Authentication exposes a reliable current-user identity to the rest of the
application. RBAC consumes that identity — authentication never queries
roles or permissions itself.

## 7. UI

Keep it minimal.

Login:

- Username/email
- Password
- Show/hide password
- Login
- Clear validation
- Loading state

After login:

- User identity available to the application
- Logout available consistently

Don't build a complicated authentication dashboard.

## 8. Audit

Record important authentication events:

- Login success
- Login failure where useful
- Logout
- Password change
- Password reset
- Account activation/deactivation

Don't store passwords or sensitive authentication secrets in the audit
log.

## 9. Performance

Authentication should be lightweight:

- One clean user lookup
- Efficient indexed login field
- No unnecessary database calls
- No repeated user queries on every frontend action
- Avoid loading roles/permissions until the authorization layer needs them

## 10. Acceptance criteria

Authentication is finished when:

- User can log in.
- Invalid credentials are rejected.
- Inactive users cannot log in.
- User can log out.
- User can change their password.
- Admin can reset a password later through the user-management layer.
- Passwords are securely hashed.
- Sessions expire securely.
- Logout/session invalidation works.
- Authentication events are auditable.
- Current-user identity can be reliably consumed by RBAC.
- Existing ERP functionality continues to work.

## Most important architectural rule

Do not let Authentication become User Management + RBAC + Permissions.
Keep the boundaries:

```text
AUTHENTICATION
    Who are you?
        ↓
USER / ORGANISATION
    Who is this user?
        ↓
RBAC / AUTHORIZATION
    What can they access?
        ↓
MODULE
    What can they do?
```

## Implementation approach

Per [`ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §16 (audit
before changing) and the roadmap's audit-first rule, the existing
authentication implementation in `jdk_clean` was audited first — see
[`../audit/AUTHENTICATION_AUDIT.md`](../audit/AUTHENTICATION_AUDIT.md) for
the full findings.

**Decision: reuse, don't rewrite.** The audit found the existing design —
FastAPI + SQLAlchemy/MySQL, bcrypt password hashing, a stateless JWT
access token paired with a server-tracked, rotating, revocable refresh
token, and a `get_current_user` resolver that stays cleanly out of
authorization's business — already matches this spec's architecture. No
new authentication framework or token strategy is being adopted. What
carries forward into Phase 1 is that implementation, hardened against the
gaps the audit found (missing audit trail, no rate limiting, an unsafe
default JWT secret, minor enumeration leaks, incomplete password policy,
weak mobile token storage — full list and priority in the audit doc)
rather than built from scratch.
