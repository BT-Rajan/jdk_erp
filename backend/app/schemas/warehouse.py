from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.validation import check_max_length


class WarehouseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    code: str
    name: str
    total_usable_storage_area: Decimal
    storage_area_unit_of_measure_id: int
    is_active: bool


class WarehouseCreateRequest(BaseModel):
    """organisation_id and code are never part of this payload -- code
    is system-generated, with no update path (see
    WarehouseUpdateRequest) -- a stable identifier a future Inventory
    module will reference should not silently change."""

    name: str
    total_usable_storage_area: Decimal = Field(max_digits=12, decimal_places=2)
    storage_area_unit_of_measure_id: int

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return check_max_length(value, 150, "Name")

    @field_validator("total_usable_storage_area")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Must be greater than zero.")
        return value


class WarehouseUpdateRequest(BaseModel):
    """Partial update, same shape as MachineUpdateRequest. `code` is
    deliberately absent -- immutable after creation. is_active has its
    own endpoint below."""

    name: str | None = None
    total_usable_storage_area: Decimal | None = Field(default=None, max_digits=12, decimal_places=2)
    storage_area_unit_of_measure_id: int | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return check_max_length(value, 150, "Name")

    @field_validator("total_usable_storage_area")
    @classmethod
    def _check_positive(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("Must be greater than zero.")
        return value


class WarehouseStatusChangeRequest(BaseModel):
    is_active: bool
