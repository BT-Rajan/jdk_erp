# JDK File / Storage Foundation

One shared storage layer. Modules never implement their own file
storage logic. Files are application data, not arbitrary filesystem
objects.

## 1. Storage abstraction

Provide one common service: `upload()`, `download()`, `delete()`,
`exists()`, `metadata()`. The application should not care whether
storage is local disk, mounted storage, or object storage later.

## 2. File metadata

Maintain a database record for each stored file: file ID,
organisation/application scope, original filename, stored filename/key,
MIME type, file size, storage location/key, uploaded by, uploaded
timestamp, related entity/record, status if processing is required.

## 3. Secure filenames

Never use the user's filename as the physical storage filename.
Generate a unique storage key.

```text
invoice.pdf
        ↓
f_8c72...pdf
```

Prevent: path traversal, executable filenames, directory manipulation,
filename collisions.

## 4. Upload validation

Validate server-side: allowed file types, actual file content/type
where practical, maximum size, filename, upload destination, user
permission. Do not rely on the browser's `accept` attribute or MIME
type supplied by the client.

## 5. Access control

A file must inherit the access rules of the record it belongs to.

```text
User cannot view Invoice 125
        ↓
User cannot download Invoice 125 attachment
```

Never expose unrestricted filesystem paths or predictable download URLs.

## 6. Download

Use an authenticated application endpoint/service: `GET /files/{file_id}`.

Server: authenticate → authorize access to related record → locate
file → stream file → return appropriate content type. Do not expose the
physical storage location.

## 7. File ↔ record relationship

Keep the storage system generic.

```text
File
 ├── entity_type
 └── entity_id
```

or a proper attachment relationship table where multiple relationships
are required. Don't create separate storage implementations for
invoice files, customer documents, production reports, employee
documents.

## 8. Deletion

Do not automatically physically delete business documents just because
a user removes an attachment. Define: logical removal, retention,
physical deletion according to the application's data-retention
requirements.

## 9. Storage security

Storage directories outside the public web root where possible. No
direct executable access. Restrict filesystem permissions. Never store
secrets/configuration alongside user files. Protect against malicious
uploads. Apply download authorization every time.

## 10. Large files

Do not load large files entirely into application memory. Use
streaming for uploads where appropriate, downloads, generated PDFs,
exports. Set sensible file-size limits.

## 11. Backup

Persistent business files must be included in the backup strategy.
Database backup alone is insufficient if the database contains
references to files.

## 12. Future storage

Start simple:

```text
Application
    ↓
Storage Service
    ↓
Local/private storage
```

Later:

```text
Application
    ↓
Storage Service
    ↓
S3 / Azure Blob / other object storage
```

The application should not need to be rewritten.

## Core rule

Files are application data, not arbitrary filesystem objects. Store
them privately, track them in the database, authorize every access,
validate every upload, and access storage only through one common
service.

## Don't build

Document management system, version-control system for files, OCR
pipeline, virus-scanning platform, object-storage abstraction
framework, complicated file workflow. Add those only when an actual
project requires them.

## Implementation approach

See `docs/audit/FILE_STORAGE_AUDIT.md` for the full verdict: what
already existed (organisation scoping via `OrganisationScopedMixin`,
the generic `entity_type`/`entity_id` shape already established by
`audit_events`, the standard error envelope), what was a genuine gap
(no storage abstraction, no secure key generation, no content
validation beyond an extension, no size enforcement while streaming, no
download endpoint, no access-control hook, no soft-delete), and what's
deliberately deferred because no business entity (Invoice, Quotation,
...) exists yet to attach a file to.
