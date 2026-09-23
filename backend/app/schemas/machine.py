from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    code: str
    name: str
    production_line_id: int
    capacity_quantity: Decimal
    capacity_unit_of_measure_id: int
    capacity_period_hours: Decimal
    is_active: bool


class MachineCreateRequest(BaseModel):
    """organisation_id is never part of this payload. `code` IS part of
    this payload and required, and -- like Product/RawMaterial -- has no
    update path (see MachineUpdateRequest): a stable identifier future
    Production/Feasibility records will reference should not silently
    change."""

    code: str
    name: str
    production_line_id: int
    capacity_quantity: Decimal
    capacity_unit_of_measure_id: int
    capacity_period_hours: Decimal

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

    @field_validator("capacity_quantity", "capacity_period_hours")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Must be greater than zero.")
        return value


class MachineUpdateRequest(BaseModel):
    """Partial update, same shape as ProductUpdateRequest. `code` is
    deliberately absent -- immutable after creation. is_active has its
    own endpoint below."""

    name: str | None = None
    production_line_id: int | None = None
    capacity_quantity: Decimal | None = None
    capacity_unit_of_measure_id: int | None = None
    capacity_period_hours: Decimal | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("capacity_quantity", "capacity_period_hours")
    @classmethod
    def _check_positive(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("Must be greater than zero.")
        return value


class MachineStatusChangeRequest(BaseModel):
    is_active: bool
