from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.validation import check_max_length


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
    min_selling_price: Decimal | None
    max_selling_price: Decimal | None
    manufacturing_lead_time_days: int | None
    customer_lead_time_days: int | None
    is_active: bool


class ProductCreateRequest(BaseModel):
    """organisation_id and code are never part of this payload -- the
    endpoint always takes organisation from the authenticated admin and
    generates code server-side, same as every other Phase 2 master
    (per explicit user instruction, superseding this module's original
    caller-supplied code -- see docs/audit/PRODUCTS_AUDIT.md #2 for the
    now-superseded jdk_clean precedent)."""

    name: str
    category_id: int
    unit_of_measure_id: int
    description: str | None = None
    selling_price: Decimal = Field(max_digits=14, decimal_places=2)
    min_selling_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    max_selling_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    manufacturing_lead_time_days: int | None = None
    customer_lead_time_days: int | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return check_max_length(value, 150, "Name")

    @field_validator("selling_price")
    @classmethod
    def _check_selling_price(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("Selling price must not be negative.")
        return value

    @field_validator("min_selling_price", "max_selling_price")
    @classmethod
    def _check_price_range_value(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Price must not be negative.")
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
    selling_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    min_selling_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
    max_selling_price: Decimal | None = Field(default=None, max_digits=14, decimal_places=2)
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
        return check_max_length(value, 150, "Name")

    @field_validator("selling_price")
    @classmethod
    def _check_selling_price(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Selling price must not be negative.")
        return value

    @field_validator("min_selling_price", "max_selling_price")
    @classmethod
    def _check_price_range_value(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Price must not be negative.")
        return value

    @field_validator("manufacturing_lead_time_days", "customer_lead_time_days")
    @classmethod
    def _check_lead_time(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("Lead time must not be negative.")
        return value


class ProductStatusChangeRequest(BaseModel):
    is_active: bool
