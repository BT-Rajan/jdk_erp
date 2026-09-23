import re

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.core.validation import normalize_email

_DIGITS_RE = re.compile(r"\D")


def _normalize_phone(value: str) -> str:
    """Same digits-only normalization as app/schemas/customer.py -- one
    rule for phone comparison across every master, not a per-module
    reinvention."""
    return _DIGITS_RE.sub("", value)


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    code: str
    name: str
    contact_person: str | None
    phone: str | None
    email: str | None
    address: str | None
    is_active: bool


class SupplierCreateRequest(BaseModel):
    """organisation_id and code are never part of this payload -- the
    endpoint always takes organisation from the authenticated admin and
    generates code server-side (docs/modules/suppliers.md #4)."""

    name: str
    contact_person: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = _normalize_phone(value)
        return normalized or None

    @field_validator("email")
    @classmethod
    def _normalize_supplier_email(cls, value: str | None) -> str | None:
        return normalize_email(value) if value is not None else value


class SupplierUpdateRequest(BaseModel):
    """Partial update, same shape as CustomerUpdateRequest. is_active has
    its own endpoint/audit action below."""

    name: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = _normalize_phone(value)
        return normalized or None

    @field_validator("email")
    @classmethod
    def _normalize_supplier_email(cls, value: str | None) -> str | None:
        return normalize_email(value) if value is not None else value


class SupplierStatusChangeRequest(BaseModel):
    is_active: bool
