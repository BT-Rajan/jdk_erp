from datetime import time

from sqlalchemy import Boolean, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import TimestampMixin


class Organisation(Base, TimestampMixin):
    """The top-level data and access boundary (docs/modules/organisation.md).
    Deliberately small -- exactly the fields the spec lists, no tenant
    settings or configuration beyond what's needed today."""

    __tablename__ = "organisations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Company email domain for validate_company_email_domain
    # (docs/modules/common_validation.md #1) -- None means no restriction.
    email_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KWD")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kuwait")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)
    # Sales same-day delivery cut-off, a Kuwait wall-clock time
    # (app/services/working_calendar_service.py). 14:00 is only the
    # default -- Admin changes it via PUT /api/organisations/me/working-calendar/cutoff,
    # never through the general organisation edit above.
    same_day_cutoff_time: Mapped[time] = mapped_column(
        Time, nullable=False, default=time(14, 0), server_default="14:00:00"
    )
