from datetime import time
from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric, String, Text, Time
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
    # Production staff available per working day -- the Admin-set
    # manpower figure the 0-2 working-day feasibility check compares
    # against (app/services/feasibility_service.py). NULL = not set, which
    # that check treats as a failure needing an Admin decision.
    production_staff_available_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Delivery Scrap Allowance % (Admin-set): the delivery tolerance a
    # future Delivery Instruction copies when it is created, so a later
    # change never alters existing deliveries. A setting only -- it never
    # changes a Sales Order quantity. 0.00-999.99, default 0.
    delivery_scrap_allowance_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    # The AI assistant's provider API key (Anthropic "sk-ant-..." -> Claude,
    # anything else -> DeepSeek), Fernet-encrypted at rest (app/core/crypto.py)
    # like a mailbox password. Admin-set; never returned in full.
    ai_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
