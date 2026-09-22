# JDK Notifications

A communication layer, not a workflow engine. Depends on
[`authentication.md`](authentication.md) (who the recipient is),
[`organisation.md`](organisation.md) (scope), and
[`background_jobs.md`](background_jobs.md) /
[`communication.md`](../../backend/README.md#communication----email-appapicommunicationpy)
for the optional email path — this module adds nothing new to either,
it only calls them.

## 1. One notification service

Every module calls the same two functions, never rolls its own insert
into a notifications table or its own email-sending code:

```text
notify(db, user, ...)
notify(db, users, ...)
```

The service handles creation, delivery (in-app always; email only when
the caller opts in) and read status. It does not decide *when* to
notify — that's each business module's own judgement (see §8).

## 2. Notification record

- notification ID
- organisation ID (scope)
- recipient user ID
- type
- title
- message
- related entity type + ID (optional — a reference, e.g. `("user", 42)`,
  never a copy of the record)
- target URL/page (optional — where clicking the notification goes)
- read/unread
- created time
- read time

## 3. In-app notification

One standard UI, not a per-module one: a bell icon with an unread
count, a dropdown list, mark-as-read (one, or all), and clicking a
notification navigates to its `target_url`. No module builds its own
notification widget.

## 4. Authorization

A user only ever sees **their own** notifications — enforced the same
way Users/Teams' directory endpoints are (`recipient_user_id ==
current_user.id`, always; see [`search.md`](search.md) §3 for the same
"narrow the caller's own scope, never a separate query" principle
applied here). That much this module enforces itself, unconditionally.

What it does **not**, and structurally cannot, enforce: whether the
*content* of a notification is something its recipient is authorized to
see is the calling module's own responsibility, at the point it calls
`notify()` — the same class of boundary as `app/core/entity_access.py`'s
registration hook for files (docs/modules/file_storage.md): this layer
has no way to re-derive an arbitrary future resource's own access rule
(a quotation's ownership/team-scope rule doesn't exist here and
shouldn't). A module must only call `notify(user, ...)` for a user who
is already authorized to view whatever the notification refers to —
exactly the same rule that already governs every other read in this
codebase (docs/modules/permissions.md's `can(user, action, resource)`),
just applied at the point a notification is created instead of at read
time.

## 5. Notification types

Fixed, generic set — a plain string, not a database enum (same
MySQL/SQLite-portability reasoning as `docs/modules/background_jobs.md`
#4's job states, `docs/modules/roles_rbac.md`'s roles, etc.):

- `INFO`
- `ACTION_REQUIRED`
- `SUCCESS`
- `WARNING`
- `ERROR`

Modules provide the actual title/message; this module only carries the
type through to the UI, which maps it to a consistent icon/tone (the
same success/warning/danger/info vocabulary `Alert`/`Badge` already
use).

## 6. Link to the source

`target_url` is a pointer, e.g. "your role was changed" links to `/`.
It never duplicates the full business record. Clicking it is an
ordinary navigation — the destination page runs its own normal
authorization check again, the same as visiting it any other way.
Nothing about a notification bypasses that.

## 7. Email integration

Optional, per call: `notify(..., send_email=True)`. When set, and the
organisation has a mailbox configured
(`app/services/email_account_service.get_smtp_credentials`), sending
goes through a background job (`send_notification_email`,
`app/jobs/send_notification_email.py`) — never inline in the request
that created the notification (`docs/modules/background_jobs.md` #2/#8:
email sending is exactly the kind of work that must not hold a request
open). No mailbox configured is not a failure — the job simply does
nothing.

```text
Business event
    ↓
notify()
    ├── In-app (always, immediate)
    └── Email (only if send_email=True and a mailbox is configured)
            └── dispatched as a background job, not sent inline
```

## 8. Don't create notifications for everything

Only meaningful events: action required, approval/rejection, an
important status change, an assignment, a failure requiring attention,
a useful system/security event. A module deciding *whether* to call
`notify()` for a given event is a judgement call this document doesn't
make for it — but "every audit event also becomes a notification" is
explicitly not the default; audit trail and notifications solve
different problems (see §9).

## 9. Retention

Read notifications are eventually purged — `cleanup_old_read_notifications`
(`app/jobs/cleanup_old_read_notifications.py`), a scheduled job in the
same style as `cleanup_expired_refresh_tokens`, deleting read
notifications older than `NOTIFICATION_RETENTION_DAYS` (default 90).
Unread notifications are never auto-deleted. Important business history
belongs in the audit trail (`docs/modules/audit_trail.md`), which has no
retention sweep — notifications are disposable UI state, the audit
trail is the permanent record.

## 10. Security

- `title`/`message` are short pointers ("Quotation Q-1024 requires
  approval"), never a dump of the underlying record.
- The email job's body is the same `title`/`message` a caller already
  chose for the in-app notification — no separate, richer email
  template that could leak more than the in-app version shows.
- Structured request logging (`docs/modules/logging_request_tracing.md`)
  never logs a notification's `title`/`message` body, the same way it
  never logs any other request/response body.

## 11. Acceptance tests

1. `notify()` creates a notification for one user, and for several at
   once.
2. A user only ever sees their own notifications — never another
   user's, even within the same organisation.
3. Unread count reflects only the caller's own unread notifications.
4. Marking one notification read only affects that notification, only
   for its own recipient (another user's/nonexistent notification ID
   returns 404, never confirming whether it belongs to someone else).
5. Mark-all-read marks every one of the caller's own unread
   notifications and no one else's.
6. `send_email=True` dispatches a background job rather than sending
   inline; the request that created the notification does not block on
   SMTP.
7. The email job is a no-op (not a failure) when the organisation has
   no mailbox configured.
8. A temporary SMTP failure retries (via `RetryableJobError`), the same
   as any other job.
9. `cleanup_old_read_notifications` deletes only read notifications past
   the retention window — an unread or recently-read one is untouched.
10. An unrecognized `type` is rejected at the point `notify()` is
    called, not silently stored.

## Core rule

One notification service + one notification UI + authorization-aware
delivery (recipient-scoped, always) + optional email through the
existing background-job system. No workflow engine, no
subscription/routing rules, no push-notification infrastructure, no
SMS/WhatsApp, no notification-rules designer — add those later if a
real requirement shows up.

## Implementation approach

Per [`../ENGINEERING_PRINCIPLES.md`](../ENGINEERING_PRINCIPLES.md) §5
("reuse before creating"): nothing new is built for delivery mechanics
that already exist — `app/services/job_service.py`'s
dispatch/retry/backoff for the email path, `app/services/email_service.py`
for actually sending, `app/core/database.py`'s `Base`/session pattern
for the record itself.

**Implemented now:**

- `app/models/notification.py` + migration `0016`.
- `app/services/notification_service.py`: `notify()`,
  `list_for_user()`, `unread_count()`, `mark_read()`,
  `mark_all_read()` — all recipient-scoped by construction (§4).
- `GET /api/notifications`, `GET /api/notifications/unread-count`,
  `PATCH /api/notifications/{id}/read`,
  `POST /api/notifications/mark-all-read`
  (`app/api/notifications.py`) — every one scoped to
  `current_user`, no admin/role gate needed since a user's own
  notifications are exactly that: their own.
- `app/jobs/send_notification_email.py`: the one real email-sending job
  type, registered the same way `cleanup_expired_refresh_tokens` is.
- `app/jobs/cleanup_old_read_notifications.py` + `NOTIFICATION_RETENTION_DAYS`
  setting + `scripts/enqueue_notification_cleanup.py`, mirroring
  `scripts/enqueue_cleanup.py` exactly (same idempotency-key-per-day
  pattern).
- Two real call sites, proven against actual events rather than left as
  unexercised infrastructure: `PATCH /api/users/{id}/role` notifies the
  affected user their role changed, and `POST /api/teams/{id}/members`
  notifies the added user — both "important status change"/"assignment"
  per §8's own examples. Neither sends email by default (§8's spam
  guidance applies to email doubly); the email path is proven by its own
  tests instead of turned on for these two.
- A frontend bell (`frontend/src/components/ui/NotificationBell.tsx`) in
  `TopNav`'s actions slot: unread count, a dropdown list, mark
  read/mark all read, click-through to `target_url`. Polls
  `/unread-count` on an interval rather than a push connection (§'s
  "don't build push-notification infrastructure").

**Deferred, not forgotten**, exactly per the spec's own "don't build"
list: a workflow/subscription/routing engine, SMS/WhatsApp, a
notification-rules designer, and real-time push (websockets) — polling
is enough at this scale, and a persistent connection is exactly the
"push-notification infrastructure" this module is told not to build.
