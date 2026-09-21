# Users Audit — `jdk_clean`

Phase 0 audit of the User entity, per [`../ROADMAP.md`](../ROADMAP.md)
and the spec in [`../modules/users.md`](../modules/users.md).

## Verdict

**Nothing new to audit here — already covered.** The User schema in
`jdk_clean` was fully audited as part of authentication (it's the same
table: `backend/schema.sql:68-101`, `backend/app/models/user.py:18-82`).
See [`AUTHENTICATION_AUDIT.md`](AUTHENTICATION_AUDIT.md) §2 for the
evidence-based findings. Restating the parts relevant to *this* module
rather than re-deriving them:

- `jdk_clean`'s `users` table already mixed identity with `role`
  (an enum column) and `department_id`/`manager_id` (profile/org-chart
  fields) directly on the user row — exactly what
  [`users.md`](../modules/users.md) §5 says not to do. That finding
  already drove a decision made during the authentication phase: this
  project's `User` model (`backend/app/models/user.py`) carries no role,
  department, or profile fields — see
  [`AUTHENTICATION_AUDIT.md`](AUTHENTICATION_AUDIT.md) §6-7. This audit
  doesn't need to repeat that decision, only confirm it still holds,
  which it does.
- `jdk_clean` had no per-organisation scoping of anything (see
  [`ORGANISATION_AUDIT.md`](ORGANISATION_AUDIT.md)), so its username/email
  uniqueness was necessarily global — there was only ever one
  organisation. That's not evidence either way for how *this* project
  should scope uniqueness now that organisations exist; see
  [`users.md`](../modules/users.md)'s implementation-approach section for
  that decision and its reasoning.
- `jdk_clean` had no organisation-scoped user directory endpoint (it
  didn't need one — single-tenant). `GET /api/users` in `jdk_clean` (if
  it existed) would have listed the whole business's users with no
  boundary to enforce; not applicable to audit for reuse since the
  boundary itself (organisation) didn't exist to test against.

## What's actually new in this phase

Everything in [`users.md`](../modules/users.md)'s "Implemented now"
section — the organisation-scoped directory endpoints, the composite
index, and the shared `UserOut` schema — is new code, not ported from
`jdk_clean`, because `jdk_clean` had no organisation boundary for a
directory endpoint to respect in the first place.
