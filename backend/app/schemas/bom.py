from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.models.bom import BOM_STATUSES


class BomComponentOut(BaseModel):
    """`percentage`/`conversion_ok`/`conversion_error` are always
    computed at read time, never stored -- docs/modules/boms.md #8's
    "choose one authoritative value: quantity." A component that was
    valid when saved can still show `conversion_ok: false` later if a
    unit's dimension or a material's conversion configuration changes
    afterward -- the same live re-check the UI's "Conversion Status"
    column is for (docs/modules/boms.md #12)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    raw_material_id: int
    quantity: Decimal
    percentage: Decimal | None
    conversion_ok: bool
    conversion_error: str | None


class BomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    product_id: int
    base_quantity: Decimal
    status: str
    notes: str | None
    components: list[BomComponentOut]


class BomCreateRequest(BaseModel):
    """organisation_id is never part of this payload. Components are
    added afterward via POST /api/boms/{id}/components, the same
    add-relationship-after-creating-the-header pattern
    SupplierMaterial/Machine already use -- a BOM always starts empty
    and `draft` (docs/modules/boms.md #10)."""

    product_id: int
    base_quantity: Decimal
    notes: str | None = None

    @field_validator("base_quantity")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Base quantity must be greater than zero.")
        return value


class BomUpdateRequest(BaseModel):
    """`product_id` is immutable -- sever (there is no delete endpoint;
    see docs/modules/boms.md #10) and create a new BOM instead of
    repointing an existing one to a different Product."""

    base_quantity: Decimal | None = None
    notes: str | None = None

    @field_validator("base_quantity")
    @classmethod
    def _check_positive(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and value <= 0:
            raise ValueError("Base quantity must be greater than zero.")
        return value


class BomComponentCreateRequest(BaseModel):
    raw_material_id: int
    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value


class BomStatusChangeRequest(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: str) -> str:
        if value not in BOM_STATUSES:
            raise ValueError(f"status must be one of {BOM_STATUSES}.")
        return value


class BomComponentUpdateRequest(BaseModel):
    """`raw_material_id` is immutable -- remove and re-add the component
    instead of repointing an existing line to a different material."""

    quantity: Decimal

    @field_validator("quantity")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Quantity must be greater than zero.")
        return value


class RequirementLine(BaseModel):
    raw_material_id: int
    required_quantity: Decimal
    unit_of_measure_id: int


class CalculateRequirementsRequest(BaseModel):
    production_quantity: Decimal

    @field_validator("production_quantity")
    @classmethod
    def _check_positive(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("Production quantity must be greater than zero.")
        return value


class CalculateRequirementsResponse(BaseModel):
    product_id: int
    production_quantity: Decimal
    requirements: list[RequirementLine]
