from sqlalchemy import Boolean, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class Category(Base, TimestampMixin, OrganisationScopedMixin):
    """The one authoritative classification master for Products/Raw
    Materials (docs/modules/categories.md #1/#3) -- audited against
    jdk_clean first (docs/audit/CATEGORIES_AUDIT.md): jdk_clean has no
    Category concept at all, just an unvalidated free-text `category`
    string independently duplicated on three unrelated tables with no
    dedup/normalization, so there is nothing to port forward. Shaped
    like Team (docs/modules/teams.md) -- name/code/description/is_active,
    no hierarchy -- since nothing in the audit justifies a parent/child
    tree for JDK's small, flat category list (#2's own "do not build
    hierarchical categories unless evidence requires it").

    `code` is system-generated (`app/core/id_formats.CATEGORY_CODE`),
    required, and immutable -- per explicit user instruction that every
    Phase 2 master's code be auto-assigned and never caller-edited,
    superseding this module's original optional/caller-editable code
    (docs/modules/categories.md #4)."""

    __tablename__ = "categories"
    __table_args__ = (
        UniqueConstraint("organisation_id", "name", name="uq_categories_organisation_id_name"),
        UniqueConstraint("organisation_id", "code", name="uq_categories_organisation_id_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
