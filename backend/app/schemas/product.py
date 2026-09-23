from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    code: str
    name: str
    category_id: int
    unit_of_measure_id: int
    description: str | None
    selling_price: Decimal
    manufacturing_lead_time_days: int | None
    customer_lead_time_days: int | None
    is_active: bool


class ProductCreateRequest(BaseModel):
    """organisation_id is never part of this payload -- the endpoint
    always takes it from the authenticated admin. Unlike Customer/
    Supplier, `code` IS part of this payload and required: jdk_clean's
    real Product code is manually assigned, not auto-generated
    (docs/audit/PRODUCTS_AUDIT.md #2), and the spec is explicit about not
    silently changing that established behaviour."""

    code: str
    name: str
    category_id: int
    unit_of_measure_id: int
    description: str | None = None
    selling_price: Decimal
    manufacturing_lead_time_days: int | None = None
    customer_lead_time_days: int | None = None

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Code is required.")
        return value

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("selling_price")
    @classmethod
    def _check_selling_price(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("Selling price must not be negative.")
        return value

    @field_validator("manufacturing_lead_time_days", "customer_lead_time_days")
    @classmethod
    def _check_lead_time(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("Lead time must not be negative.")
        return value


class ProductUpdateRequest(BaseModel):
    """Partial update, same shape as CustomerUpdateRequest -- every field
    optional so a caller sends only what changed. `code` is deliberately
    absent: jdk_clean's own ProductUpdate schema has no code field at all
    (docs/audit/PRODUCTS_AUDIT.md #2), so a Product's code is immutable
    after creation here too. is_active has its own endpoint below."""

    name: str | None = None
    category_id: int | None = None
    unit_of_measure_id: int | None = None
    description: str | None = None
    selling_price: Decimal | None = None
    manufacturing_lead_time_days: int | None = None
    customer_lead_time_days: int | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("selling_price")
    @classmethod
    def _check_selling_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Selling price must not be negative.")
        return value

    @field_validator("manufacturing_lead_time_days", "customer_lead_time_days")
    @classmethod
    def _check_lead_time(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("Lead time must not be negative.")
        return value


class ProductStatusChangeRequest(BaseModel):
    is_active: bool
