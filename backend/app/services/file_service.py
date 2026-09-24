import re
import uuid
from datetime import datetime
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.entity_access import get_entity_access_check
from app.core.errors import AccessDeniedError, NotFoundError, ValidationError
from app.core.storage import StorageBackend, default_storage
from app.models.file import FileRecord
from app.models.user import User

# Signature-checked against the claimed extension before anything is
# written to storage (docs/modules/file_storage.md #4: "actual file
# content/type where practical") -- an allow-list, so an unrecognized
# extension is rejected by construction rather than needing a matching
# deny-list of dangerous ones (docs/modules/file_storage.md #3/#9).
# None means "no reliable magic bytes" (plain text/csv) -- accepted on
# extension alone for those two.
_SIGNATURES: dict[str, tuple[bytes, ...] | None] = {
    "pdf": (b"%PDF",),
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpg": (b"\xff\xd8\xff",),
    "jpeg": (b"\xff\xd8\xff",),
    "gif": (b"GIF87a", b"GIF89a"),
    # .docx/.xlsx are zip containers -- same signature as any other zip.
    "docx": (b"PK\x03\x04",),
    "xlsx": (b"PK\x03\x04",),
    "csv": None,
}

_MIME_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}

_SAFE_DISPLAY_NAME_RE = re.compile(r"[^A-Za-z0-9 ._-]")
_SNIFF_BYTES = 16


def sanitize_display_filename(filename: str) -> str:
    """The *display* name, stored for the user's benefit only -- never
    used to build a filesystem path (docs/modules/file_storage.md #3).
    Strips path separators and anything that isn't a plain, printable
    filename character; a request with `../../etc/passwd\\0.pdf` still
    stores/returns a harmless string, not a path or a header-injection
    vector in the download's Content-Disposition."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = _SAFE_DISPLAY_NAME_RE.sub("_", name).strip(" .")
    return name or "file"


def _extension(filename: str) -> str:
    if "." not in filename:
        raise ValidationError("File must have a recognized extension.", fields={"file": "Missing file extension."})
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in settings.allowed_upload_extensions:
        raise ValidationError(
            f"'.{ext}' files are not allowed.", fields={"file": f"'.{ext}' files are not allowed."}
        )
    return ext


def _sniff_and_validate(extension: str, header: bytes) -> None:
    signatures = _SIGNATURES.get(extension)
    if signatures is None:
        return
    if not any(header.startswith(sig) for sig in signatures):
        raise ValidationError(
            f"File content does not match a valid .{extension} file.",
            fields={"file": "File content does not match its extension."},
        )


def generate_storage_key(extension: str) -> str:
    """Never derived from the user's filename (docs/modules/file_storage.md
    #3) -- a fresh random key every time, so collisions, path traversal
    and directory manipulation are all structurally impossible rather
    than merely checked for."""
    return f"f_{uuid.uuid4().hex}.{extension}"


class _LimitedStream:
    """Wraps an upload's file object so upload_file() enforces
    MAX_UPLOAD_SIZE_MB while streaming to storage, rather than after
    buffering the whole thing (docs/modules/file_storage.md #10) --
    StorageBackend.upload() itself stays generic and size-limit-agnostic."""

    def __init__(self, source: BinaryIO, max_bytes: int):
        self._source = source
        self._max_bytes = max_bytes
        self._read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._source.read(size)
        self._read += len(chunk)
        if self._read > self._max_bytes:
            raise ValidationError(
                f"File exceeds the {self._max_bytes // (1024 * 1024)}MB upload limit.",
                fields={"file": "File is too large."},
            )
        return chunk


def upload_file(
    db: Session,
    *,
    organisation_id: int,
    uploaded_by_user_id: int,
    filename: str,
    stream: BinaryIO,
    entity_type: str | None = None,
    entity_id: int | None = None,
    storage: StorageBackend = default_storage,
) -> FileRecord:
    """Validate before opening the transaction, apply the authoritative
    change (the storage write) before the database write, commit once
    (docs/modules/database_transaction_integrity.md #6/#9). Extension
    and content-signature validation never touch storage; only a file
    that passes both is ever written."""
    extension = _extension(filename)
    header = stream.read(_SNIFF_BYTES)
    stream.seek(0)
    _sniff_and_validate(extension, header)

    key = generate_storage_key(extension)
    limited = _LimitedStream(stream, settings.max_upload_size_bytes)
    try:
        size_bytes = storage.upload(key, limited)
    except ValidationError:
        storage.delete(key)  # remove whatever partial bytes were written
        raise

    record = FileRecord(
        organisation_id=organisation_id,
        original_filename=sanitize_display_filename(filename),
        storage_key=key,
        mime_type=_MIME_TYPES[extension],
        size_bytes=size_bytes,
        entity_type=entity_type,
        entity_id=entity_id,
        uploaded_by_user_id=uploaded_by_user_id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_file_or_404(db: Session, file_id: int, organisation_id: int) -> FileRecord:
    """Scoped to the caller's own organisation -- a file from another
    organisation is 404, not 403, so its existence is never confirmed
    (docs/modules/file_storage.md #5/#6, same pattern as every other
    cross-organisation lookup in this project)."""
    record = (
        db.query(FileRecord)
        .filter(FileRecord.id == file_id, FileRecord.organisation_id == organisation_id, FileRecord.deleted_at.is_(None))
        .first()
    )
    if record is None:
        raise NotFoundError("File not found.")
    return record


def authorize_file_access(db: Session, user: User, record: FileRecord) -> None:
    """Organisation-scoping (already enforced by get_file_or_404) is the
    baseline; when the file is linked to an entity_type a module has
    registered a checker for, that checker also has to allow it
    (docs/modules/file_storage.md #5: "a file must inherit the access
    rules of the record it belongs to"). No entity type is registered
    yet, so this is a no-op today -- the mechanism exists for the first
    module that needs it."""
    if record.entity_type is None or record.entity_id is None:
        return
    checker = get_entity_access_check(record.entity_type)
    if checker is not None and not checker(db, user, record.entity_id):
        raise AccessDeniedError("You do not have permission to access this file.")


def attach_files(
    db: Session, *, file_ids: list[int], entity_type: str, entity_id: int, organisation_id: int
) -> list[FileRecord]:
    """Links already-uploaded (POST /api/files, entity_type/entity_id
    omitted) files to the entity that now exists to own them -- the
    "attach-then-save" two-step flow the FileRecord model was already
    documented as supporting (see its own docstring: "an
    uploaded-but-not-yet-linked file... has no entity yet"). Used by
    app/api/rfqs.py's capture-response action, its first real caller
    (docs/modules/rfq.md #17). Only files already in the caller's own
    organisation and not yet linked to a different entity are accepted
    -- never silently re-parents a file already attached elsewhere."""
    records = db.query(FileRecord).filter(FileRecord.id.in_(file_ids), FileRecord.organisation_id == organisation_id).all()
    if len(records) != len(set(file_ids)):
        raise ValidationError(
            "One or more files could not be found in your organisation.",
            fields={"file_ids": "One or more files are invalid."},
        )
    for record in records:
        if record.entity_type is not None and (record.entity_type != entity_type or record.entity_id != entity_id):
            raise ValidationError(
                "One or more files are already attached elsewhere.",
                fields={"file_ids": "One or more files are already attached to a different record."},
            )
        record.entity_type = entity_type
        record.entity_id = entity_id
        db.add(record)
    db.flush()
    return records


def soft_delete_file(db: Session, record: FileRecord) -> None:
    """Logical removal only (docs/modules/file_storage.md #8) -- never
    touches the physical file. Physical deletion is a separate,
    deliberate retention-policy operation this phase doesn't implement,
    since no retention policy exists yet to implement it against."""
    record.deleted_at = datetime.utcnow()
    db.add(record)
    db.commit()
