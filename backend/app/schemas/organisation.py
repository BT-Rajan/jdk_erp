from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.validation import normalize_email


class OrganisationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    contact_email: str | None
    contact_phone: str | None
    address: str | None
    email_domain: str | None
    currency: str
    timezone: str
    production_staff_available_per_day: int | None = None
    delivery_scrap_allowance_percent: Decimal = Decimal("0")
    is_active: bool


class OrganisationUpdateRequest(BaseModel):
    """docs/modules/organisation.md #6 -- editing the organisation's own
    record. Every field is optional so a caller can send only what
    changed (PATCH semantics); `id`/`organisation_id`/`is_active` are
    deliberately absent -- there is no `id` to change (the endpoint
    always targets the caller's own organisation) and `is_active` has
    its own endpoint/audit action below, since deactivating is a much
    more consequential change than editing contact details."""

    name: str | None = None
    code: str | None = None
    contact_email: EmailStr | None = None
    contact_phone: str | None = None
    address: str | None = None
    email_domain: str | None = None
    currency: str | None = None
    timezone: str | None = None
    production_staff_available_per_day: int | None = Field(default=None, ge=0)
    # Percent, 0-999.99 with at most 2 decimal places (Numeric(5, 2));
    # never rounded silently -- a value it can't store exactly is refused.
    delivery_scrap_allowance_percent: Decimal | None = Field(
        default=None, ge=0, le=Decimal("999.99"), max_digits=5, decimal_places=2
    )

    @field_validator("delivery_scrap_allowance_percent")
    @classmethod
    def _allowance_required(cls, value: Decimal | None) -> Decimal | None:
        # Sent explicitly as null: the setting always has a value (0 = none).
        if value is None:
            raise ValueError("must be a number; use 0 for no allowance")
        # Exact (at most 2 places are allowed above): stored and audited as e.g. 3.00.
        return value.quantize(Decimal("0.01"))

    @field_validator("name", "code")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value is not None else value

    @field_validator("contact_email")
    @classmethod
    def _normalize_contact_email(cls, value: str | None) -> str | None:
        return normalize_email(value) if value is not None else value

    @field_validator("currency")
    @classmethod
    def _check_currency(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().upper()
        if len(value) != 3 or not value.isalpha():
            raise ValueError("currency must be a 3-letter ISO 4217 code, e.g. 'KWD'")
        return value

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"'{value}' is not a recognized timezone.") from exc
        return value


class OrganisationStatusChangeRequest(BaseModel):
    is_active: bool
