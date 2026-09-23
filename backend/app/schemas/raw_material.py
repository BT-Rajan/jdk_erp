from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class RawMaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    code: str
    name: str
    category_id: int
    unit_of_measure_id: int
    description: str | None
    reference_cost: Decimal | None
    is_active: bool


class RawMaterialCreateRequest(BaseModel):
    """organisation_id is never part of this payload -- the endpoint
    always takes it from the authenticated admin. `code` IS part of this
    payload and required: jdk_clean's real Raw Material code is manually
    assigned, not auto-generated, same as Product
    (docs/audit/RAW_MATERIALS_AUDIT.md #2)."""

    code: str
    name: str
    category_id: int
    unit_of_measure_id: int
    description: str | None = None
    reference_cost: Decimal | None = None

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

    @field_validator("reference_cost")
    @classmethod
    def _check_reference_cost(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Reference cost must not be negative.")
        return value


class RawMaterialUpdateRequest(BaseModel):
    """Partial update, same shape as ProductUpdateRequest. `code` is
    deliberately absent -- immutable after creation, same as Product.
    is_active has its own endpoint below."""

    name: str | None = None
    category_id: int | None = None
    unit_of_measure_id: int | None = None
    description: str | None = None
    reference_cost: Decimal | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("reference_cost")
    @classmethod
    def _check_reference_cost(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Reference cost must not be negative.")
        return value


class RawMaterialStatusChangeRequest(BaseModel):
    is_active: bool


class SupplierMaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    supplier_id: int
    raw_material_id: int
    supplier_material_code: str | None
    purchase_price: Decimal | None
    lead_time_days: int | None
    moq: Decimal | None
    max_supply_quantity: Decimal | None
    is_preferred: bool
    is_active: bool


class SupplierMaterialCreateRequest(BaseModel):
    """raw_material_id is never part of this payload -- it comes from the
    path (POST /api/raw-materials/{raw_material_id}/suppliers)."""

    supplier_id: int
    supplier_material_code: str | None = None
    purchase_price: Decimal | None = None
    lead_time_days: int | None = None
    moq: Decimal | None = None
    max_supply_quantity: Decimal | None = None
    is_preferred: bool = False

    @field_validator("purchase_price", "moq", "max_supply_quantity")
    @classmethod
    def _check_non_negative_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Must not be negative.")
        return value

    @field_validator("lead_time_days")
    @classmethod
    def _check_lead_time(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("Lead time must not be negative.")
        return value


class SupplierMaterialUpdateRequest(BaseModel):
    """Partial update. `supplier_id`/`raw_material_id` are immutable --
    sever the relationship (DELETE) and create a new one instead of
    repointing an existing row."""

    supplier_material_code: str | None = None
    purchase_price: Decimal | None = None
    lead_time_days: int | None = None
    moq: Decimal | None = None
    max_supply_quantity: Decimal | None = None
    is_preferred: bool | None = None
    is_active: bool | None = None

    @field_validator("purchase_price", "moq", "max_supply_quantity")
    @classmethod
    def _check_non_negative_decimal(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value < 0:
            raise ValueError("Must not be negative.")
        return value

    @field_validator("lead_time_days")
    @classmethod
    def _check_lead_time(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("Lead time must not be negative.")
        return value
