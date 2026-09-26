import re

from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.core.validation import check_max_length, normalize_email

_DIGITS_RE = re.compile(r"\D")


def _normalize_phone(value: str) -> str:
    """Digits-only, so "+965 1234 5678" / "965-1234-5678" / "96512345678"
    compare and store identically -- normalized once at write time
    (docs/audit/CUSTOMERS_AUDIT.md), not re-derived on every read the way
    jdk_clean's O(n) duplicate-phone scan did."""
    return _DIGITS_RE.sub("", value)


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    code: str
    name: str
    contact_person: str | None
    phone: str | None
    email: str | None
    address: str | None
    assigned_to_user_id: int | None
    is_active: bool
    payment_arrangement: str | None = None
    payment_plan_details: str | None = None


class CustomerCreateRequest(BaseModel):
    """organisation_id and code are never part of this payload -- the
    endpoint always takes organisation from the authenticated user and
    generates code server-side (docs/modules/customers.md #4).
    assigned_to_user_id is accepted but only an admin/manager caller may
    set it to someone other than themselves -- a team_member's own
    customers are always auto-assigned to them (see create_customer)."""

    name: str
    contact_person: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    assigned_to_user_id: int | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return check_max_length(value, 150, "Name")

    @field_validator("contact_person")
    @classmethod
    def _check_contact_person(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return check_max_length(value, 120, "Contact person") if value else None

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = _normalize_phone(value)
        return check_max_length(normalized, 30, "Phone") if normalized else None

    @field_validator("email")
    @classmethod
    def _normalize_customer_email(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return check_max_length(normalize_email(value), 120, "Email")


class CustomerUpdateRequest(BaseModel):
    """Partial update, same shape as CategoryUpdateRequest. is_active and
    assigned_to_user_id each have their own endpoint/audit action below --
    both are more consequential changes than editing contact details."""

    name: str | None = None
    contact_person: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    address: str | None = None
    # Admin-only, like every field here (S14.2): payment before delivery,
    # after delivery, or an Admin-approved plan whose terms go in
    # payment_plan_details. Null clears it.
    payment_arrangement: Literal["before_delivery", "after_delivery", "payment_plan"] | None = None
    payment_plan_details: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return check_max_length(value, 150, "Name")

    @field_validator("contact_person")
    @classmethod
    def _check_contact_person(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return check_max_length(value, 120, "Contact person") if value else None

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = _normalize_phone(value)
        return check_max_length(normalized, 30, "Phone") if normalized else None

    @field_validator("payment_plan_details")
    @classmethod
    def _check_plan_details(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return check_max_length(value, 2000, "Payment plan details") if value else None

    @field_validator("email")
    @classmethod
    def _normalize_customer_email(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return check_max_length(normalize_email(value), 120, "Email")


class CustomerStatusChangeRequest(BaseModel):
    is_active: bool


class CustomerAssignRequest(BaseModel):
    # None is a valid, deliberate value here -- it un-assigns the
    # customer back to the unassigned/prospect pool, distinct from
    # simply omitting the field on a partial update.
    assigned_to_user_id: int | None
