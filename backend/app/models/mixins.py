from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    # Set in Python (UTC), not via DB server_default -- keeps timestamps
    # consistent regardless of the DB server's own timezone configuration.
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class OrganisationScopedMixin:
    """The one definition of "how a table belongs to an organisation"
    (docs/modules/organisation.md #3/#8) -- every future organisation-owned
    table (customers, products, orders, ...) mixes this in instead of
    redeclaring the column, so the FK and index can't drift between
    modules."""

    organisation_id: Mapped[int] = mapped_column(ForeignKey("organisations.id"), nullable=False, index=True)
