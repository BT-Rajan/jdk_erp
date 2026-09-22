# File / Storage Foundation Audit

Verdict on `docs/modules/file_storage.md` against the existing code.
No business entity (Invoice, Quotation, ...) exists yet in this repo,
so this audit covers the storage layer itself plus the extensibility
hook a future entity-owning module will need.

## Already present, reused as-is

- **Organisation scoping.** `OrganisationScopedMixin` (built for
  Organisation/Teams/Permissions) gives `files.organisation_id` the same
  required, indexed, `RESTRICT`-on-delete foreign key every other table
  uses — no new pattern invented.
- **The generic `entity_type`/`entity_id` shape.** `audit_events` already
  established this exact pattern for "which record is this about,
  without a table per module." `files` reuses it verbatim (#7).
- **The standard error envelope and organisation-scoped 404 pattern.**
  A file from another organisation returns `NotFoundError` (404), never
  `AccessDeniedError` (403) — the same "never confirm another
  organisation's row exists" rule already used by every other
  cross-organisation lookup in this project (users, teams).
- **One-commit business transaction.** `upload_file()` writes to storage
  *before* the database insert and commits once
  (`docs/modules/database_transaction_integrity.md #6/#9`), the same
  validate-then-transact shape already established for login/refresh.
- **Explicit `ON DELETE` on every new foreign key**
  (`docs/modules/database_transaction_integrity.md #2`): `RESTRICT` for
  `organisation_id`, `SET NULL` for `uploaded_by_user_id` (deliberately
  different from `audit_events.user_id` — see below).

## Genuine gaps filled

1. **No storage abstraction existed at all.** Added
   `app/core/storage.py`: a `StorageBackend` protocol
   (`upload`/`download`/`delete`/`exists`/`metadata`) and
   `LocalStorageBackend`, the "start simple" step (#12). A future
   S3/Azure Blob backend is one new class implementing the same
   protocol — no caller changes.
2. **No secure key generation.** `generate_storage_key()` never touches
   the user's filename — a fresh `f_<uuid4 hex>.<ext>` every call (#3).
   `original_filename` is stored separately, sanitized
   (`sanitize_display_filename()` strips path separators and anything
   outside a safe printable set) for display/`Content-Disposition`
   only, never for a filesystem path.
3. **No content validation beyond a file extension.** Client-supplied
   `Content-Type` is never trusted (#4). Each allow-listed extension
   (`ALLOWED_UPLOAD_EXTENSIONS`, an allow-list rather than a deny-list of
   dangerous ones — #3/#9) has an expected magic-byte signature; the
   first bytes of the upload are sniffed and checked against it before
   anything is written to storage. Verified directly: a `.pdf`-named
   upload whose content actually starts with `MZ` (an executable) is
   rejected with `422`, never reaches disk.
4. **No size enforcement during streaming.** `_LimitedStream` wraps the
   upload's file object and raises once `MAX_UPLOAD_SIZE_MB` is
   exceeded, checked chunk-by-chunk *while* streaming to storage (#10) —
   never after buffering the whole file into memory. A partial write
   left behind by a rejected oversized upload is cleaned up
   immediately. Verified directly: an oversized upload leaves zero
   files on disk and zero rows in the database.
5. **No download endpoint.** Added `GET /api/files/{file_id}`:
   authenticate → load scoped to the caller's organisation (404 if
   missing or cross-organisation) → `authorize_file_access` → stream via
   `StorageBackend.download()`'s generator, so a large file is never
   fully read into memory (#6/#10). The response never includes
   `storage_key` — verified directly in `FileOut`'s schema and a test
   asserting it's absent from the JSON body.
6. **No access-control hook for "inherit the access rules of the record
   it belongs to" (#5).** Added `app/core/entity_access.py`: a small
   registry a future module registers an `entity_type` checker into.
   Organisation-scoping is the baseline, checked first and always;
   the registered checker (if any) is an *additional* gate on top,
   never a replacement for it. No entity type is registered today, so
   this is a no-op in practice — the mechanism exists, the business
   rule doesn't yet, matching this project's established "common layer
   provides the mechanism, the module provides the rule" boundary
   (`docs/modules/common_validation.md #6`).
7. **No soft-delete.** `DELETE /api/files/{file_id}` sets `deleted_at`
   only (#8) — the physical file is untouched, verified directly by a
   test that deletes a file via the API and then confirms
   `LocalStorageBackend.exists()` still returns `True` for its key.
   Physical deletion/retention policy is not implemented: no such
   policy exists yet to implement it against.

## A deliberate `ON DELETE` difference from `audit_events`

`files.uploaded_by_user_id` uses `SET NULL`, not `RESTRICT` like
`audit_events.organisation_id`. Reasoning: `audit_events` **is** the
audit trail — an audit row must never be silently orphaned by a delete
succeeding elsewhere. A file's `uploaded_by_user_id` is provenance
metadata *about* the file, not the record of value itself (the file and
its `files` row are); losing that attribution on a user removal must
not block the removal. `files.organisation_id` is still `RESTRICT`,
same reasoning as every other organisation-scoped table: organisations
are deactivated, never deleted, and the file must not be silently
reachable from nowhere.

## Reviewed, not built

- **Storage location outside the public web root (#9).** Trivially true
  today: this application serves no static files or public directory at
  all, so there is no web root to collide with. `FILE_STORAGE_ROOT`
  defaults to a private, non-served directory regardless.
- **Backup (#11).** Application-code has nothing to do here — this is a
  deployment/ops concern (the storage directory must be included in
  whatever backs up the database). Documented in the backend README as
  an operational requirement, not implemented as code.
- **Large generated-PDF/export streaming (#10).** No PDF-generation or
  export feature exists yet (`app/core/qr.py` generates small in-memory
  PNGs, not large files) — `StorageBackend.upload()`/`download()` are
  already chunked/streaming, so whichever module first generates a
  large file has the mechanism ready without further work here.
- **Upload permission gating beyond authentication (#4's "user
  permission").** Any authenticated user can upload today. The actual
  permission that matters — "can this user attach a file to Invoice
  125" — belongs to the module that owns Invoice, via the same
  `entity_access` registry described above; there is no such module yet
  to gate against.

## Don't build (per the spec's own list) — confirmed not built

No document-management system, no file version control, no OCR
pipeline, no virus-scanning platform, no object-storage abstraction
framework beyond the one small `StorageBackend` protocol, no
complicated file workflow.

## What's added

| Area | File |
| --- | --- |
| Storage abstraction (local disk) | `app/core/storage.py` |
| File metadata table | `app/models/file.py`, migration `0013` |
| Upload validation, key generation, soft delete | `app/services/file_service.py` |
| Entity-access extensibility hook | `app/core/entity_access.py` |
| Upload/download/delete endpoints | `app/api/files.py` |
| Response schema (never exposes storage_key) | `app/schemas/file.py` |
| Settings (`FILE_STORAGE_ROOT`, `MAX_UPLOAD_SIZE_MB`, `ALLOWED_UPLOAD_EXTENSIONS`) | `app/core/config.py` |
| Tests | `backend/tests/test_files.py` |
