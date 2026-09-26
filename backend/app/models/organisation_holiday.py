from datetime import date

from sqlalchemy import Date, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class OrganisationHoliday(Base, TimestampMixin, OrganisationScopedMixin):
    """One Admin-configured non-working date on the organisation's single
    working calendar (app/services/working_calendar_service.py). The
    weekly working pattern (Sunday-Thursday) is a fixed business rule,
    not data, so holidays are the only calendar rows stored. At most one
    row per organisation per date."""

    __tablename__ = "organisation_holidays"
    __table_args__ = (
        UniqueConstraint("organisation_id", "holiday_date", name="uq_organisation_holidays_organisation_id_holiday_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(120), nullable=False)
