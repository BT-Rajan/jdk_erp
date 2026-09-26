# JDK ERP — Login, Authentication, RBAC & Access Control

Reference manual for the identity and access layer: signing in, session
handling, user accounts, roles, teams, and permission scope. Each entry
gives the screen path, who can use it, and what it does.

---

## 1. Core model (read this first)

```
Authentication  → Who are you?            (login/session)
User            → Which person, which org  (identity record)
Role            → What authority           (Super Admin / Admin / Manager / Team Member)
Team            → Which department(s)      (many per user)
Permission      → What action, what scope  (ALL / TEAM / OWN)
```

- **Role** sets baseline authority.
- **Team membership** sets organisational scope (a user can be in several teams).
- **Ownership** marks whose record it is.
- **Permission + scope** decides, per module/action, what's actually visible or editable.

### Roles at a glance

| Role | Meaning | Default scope |
|---|---|---|
| Super Admin | Full authority; can create organisations | ALL |
| Admin | Full authority within own organisation | ALL (within org) |
| Manager | Runs their team(s) | TEAM |
| Team Member | Does their own work | OWN |

### Scope values

| Scope | Meaning |
|---|---|
| ALL | Every permitted record in the organisation |
| TEAM | Records belonging to the user's assigned team(s) |
| OWN | Only records the user owns/is assigned to |

Only **Super Admin / Admin** manage users, roles, team membership, and
permission overrides. **Manager** cannot grant privileges. **Team
Member** cannot manage access at all. No one can change their own role
or deactivate their own account.

---

## 2. Authentication — screens & transactions

### 2.1 Log in
- **Navigate:** `/login` (public — no sign-in required)
- **Who:** anyone with an account
- **Fields:** Username, Password (show/hide toggle) → **Sign in** button
- **Outcomes:**
  - Correct credentials, active account → redirected to the page they originally wanted, or Dashboard (`/`)
  - Wrong username or wrong password → same generic error, "Invalid username or password." (deliberately identical — doesn't reveal which)
  - Inactive account → same generic error as above
  - 5 failed attempts on one username within 15 minutes → locked out, "Too many failed login attempts. Please try again later."

### 2.2 Log out
- **Navigate:** top-right account chip (shows name + role) → **Sign out**
- **Who:** any signed-in user
- **Does:** revokes the session's refresh token server-side, clears local session, returns to `/login`

### 2.3 Change my own password
- **Navigate:** no screen yet — backend endpoint only (`POST /api/auth/change-password`)
- **Who:** any signed-in user, for their own account
- **Needs:** current password (verified) + new password (must differ from current, must meet password policy below)
- **Does:** on success, signs the user out **everywhere** — every other active session/device is force-logged-out

### 2.4 Session behaviour (automatic, no screen)
- Access token: valid 60 minutes, silently refreshed in the background
- Refresh token (the "session"): expires after 7 days absolute, **or** 12 hours of inactivity, whichever comes first
- Expired/invalid session → next request bounces the user to `/login`
- Deactivating a user, changing their role, or changing their password all immediately revoke that user's other active sessions

### Password policy
- Minimum 8 characters
- At least 1 uppercase letter
- At least 1 number
- At least 1 special character
- Never shown back through the app or an API response once set

---

## 3. User management — screens & transactions

All under **Settings → Users** (`/users`). Only visible in the nav to
**Admin/Super Admin**; a Manager or Team Member who opens the URL
directly sees "Only an organisation admin can manage users." instead of
the table.

### 3.1 View users
- **Navigate:** Settings → Users
- **Who:** Admin, Super Admin
- **Shows:** Name, Email, Username, Role, Teams, Status (Active/Inactive)
- **Options:** search by name/email/username; sort any column; paginated list

### 3.2 Create a user
- **Navigate:** Settings → Users → **New User** button (opens a form)
- **Who:** Admin, Super Admin
- **Fields:** Full name, Email, Username, Password, Role, Teams (optional, multi-select)
- **Does:** creates the account, applies the password policy, rejects a duplicate email/username

### 3.3 Change a user's role
- **Navigate:** Settings → Users → row's **Actions** menu → "Set role: <Role>"
- **Who:** Admin, Super Admin
- **Options:** any of the 3 roles other than the user's current one
- **Not allowed:** changing your own role
- **Does:** takes effect immediately; forces that user to sign in again everywhere

### 3.4 Activate / deactivate a user
- **Navigate:** Settings → Users → row's **Actions** menu → "Activate" / "Deactivate" → confirm dialog
- **Who:** Admin, Super Admin
- **Not allowed:** deactivating your own account
- **Does:** deactivated user can no longer log in; all of their active sessions are revoked immediately; reactivating restores login access

### 3.5 Assign a user to teams
- **Navigate:** only available at creation time (the Teams field in **New User**)
- **Who:** Admin, Super Admin
- **Note:** editing an existing user's team membership after creation has no screen yet — it exists only as a backend API (add/remove team member), not exposed in the UI today

---

## 4. Roles, teams & permissions — capabilities without a screen yet

These exist and are enforced, but are **API-only today** — there is no
menu item or page for them. Listed so the assistant doesn't describe a
screen that isn't there.

| Capability | Who | Notes |
|---|---|---|
| Add/remove a user's team membership after creation | Admin, Super Admin | No UI; API only |
| Override a role's default permission/scope for a module+action | Admin, Super Admin | No UI; API only |
| Override one specific user's permission/scope for a module+action | Admin, Super Admin | No UI; API only |
| Check my own effective permission/scope for a module+action | any signed-in user | No UI; API only, self-service |
| Browse the security audit log | Admin, Super Admin | No UI; API only |

---

## 5. What gets audit-logged

Recorded automatically, not user-visible in a screen yet (see §4):

- Login success / login failure (with reason, never the password)
- Logout
- Password change
- Role changed
- Team added / team removed
- User created
- User activated / deactivated

---

## 6. Quick answers

- **"I forgot my password"** → no self-service reset; an Admin/Super Admin must give a new one via the account (today: recreate/communicate a new password — a dedicated admin-reset action isn't built yet).
- **"Why was I signed out?"** → idle over 12 hours, session older than 7 days, an admin changed your role/status, or you changed your own password.
- **"Why can't I see Settings → Users?"** → that menu only shows for Admin/Super Admin.
- **"Can a Manager create users or change roles?"** → no — user creation, role changes, activation/deactivation, and permission overrides are Admin/Super Admin only.
- **"Can I manage my own team or role?"** → no — no self-service for role, status, or organisation; always an Admin/Super Admin action, and never on your own account.
