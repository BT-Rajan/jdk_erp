from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class FileRecord(Base, TimestampMixin, OrganisationScopedMixin):
    """The one database record per stored file (docs/modules/file_storage.md
    #2) -- storage_key is the physical name LocalStorageBackend
    (app/core/storage.py) actually reads/writes; original_filename is
    display-only and never touches the filesystem (#3). entity_type/
    entity_id is the generic file<->record relationship #7 asks for, so
    a future Invoice/Quotation/etc. attachment reuses this table rather
    than each module building its own. deleted_at is logical removal
    only (#8) -- soft-deleting a row never touches the physical file;
    physical deletion is a separate, deliberate retention-policy
    operation this phase doesn't implement (no such policy exists yet)."""

    __tablename__ = "files"
    __table_args__ = (Index("ix_files_entity_type_entity_id", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Nullable: an uploaded-but-not-yet-linked file (e.g. attach-then-save
    # forms) has no entity yet. No FK to a concrete table -- there isn't
    # one yet, and #7 explicitly wants this generic, not one storage
    # implementation per business module.
    entity_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SET NULL, not RESTRICT: unlike audit_events this isn't itself the
    # audit trail (docs/modules/database_transaction_integrity.md #2) --
    # the file and its metadata are the record of value; who uploaded it
    # is informational and must not block a user removal.
    uploaded_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Free-form, like audit_events.module/permissions.module_key -- "ready"
    # covers every file today (no processing pipeline exists yet); a
    # future thumbnail/scan/convert step sets its own value rather than
    # this file growing a fixed enum.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ready")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
