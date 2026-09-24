from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin

RFQ_DOCUMENT = "rfq"
DOCUMENT_TYPES = (RFQ_DOCUMENT,)


class DocumentTemplate(Base, TimestampMixin, OrganisationScopedMixin):
    """Admin-configured letterhead and wording for one generated document
    type (docs/modules/rfq.md #11). `letterhead_file_id` is a full A4
    page image (PNG/JPEG) drawn behind every page; the margins keep the
    generated content clear of its printed header/footer."""

    __tablename__ = "document_templates"
    __table_args__ = (
        UniqueConstraint("organisation_id", "document_type", name="uq_document_templates_org_id_document_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_type: Mapped[str] = mapped_column(String(20), nullable=False)
    letterhead_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("files.id", ondelete="SET NULL"), nullable=True
    )
    margin_top_mm: Mapped[int] = mapped_column(Integer, nullable=False, default=40, server_default="40")
    margin_bottom_mm: Mapped[int] = mapped_column(Integer, nullable=False, default=25, server_default="25")
    intro_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    terms_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_text: Mapped[str | None] = mapped_column(Text, nullable=True)
