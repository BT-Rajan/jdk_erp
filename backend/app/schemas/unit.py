from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class UnitOfMeasureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    name: str
    code: str
    description: str | None
    dimension: str | None
    conversion_factor_to_base: Decimal | None
    is_active: bool


def _normalize_code(value: str) -> str:
    """Upper-cased and stripped -- the exact "kg"/"Kg"/"KGS" drift
    jdk_clean's own history shows free text produces
    (docs/audit/UNITS_OF_MEASURE_AUDIT.md), guarded against here rather
    than relying on every caller to normalize consistently."""
    value = value.strip().upper()
    if not value:
        raise ValueError("Code is required.")
    return value


def _check_dimension_pair(dimension: str | None, factor: Decimal | None) -> None:
    """dimension/conversion_factor_to_base are both-or-neither -- a unit
    either fully participates in universal conversion (docs/modules/boms.md
    #3) or carries no conversion state at all (docs/audit/BOMS_AUDIT.md #4:
    a half-configured unit is exactly the kind of ambiguity a BOM
    component validation must never have to guess about)."""
    if (dimension is None) != (factor is None):
        raise ValueError("dimension and conversion_factor_to_base must be provided together, or not at all.")
    if factor is not None and factor <= 0:
        raise ValueError("conversion_factor_to_base must be greater than zero.")


class UnitOfMeasureCreateRequest(BaseModel):
    """organisation_id is never part of this payload -- the endpoint
    always takes it from the authenticated admin (docs/modules/organisation.md #3)."""

    name: str
    code: str
    description: str | None = None
    dimension: str | None = None
    conversion_factor_to_base: Decimal | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str) -> str:
        return _normalize_code(value)

    @field_validator("dimension")
    @classmethod
    def _strip_dimension(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def _check_dimension_and_factor(self) -> "UnitOfMeasureCreateRequest":
        _check_dimension_pair(self.dimension, self.conversion_factor_to_base)
        return self


class UnitOfMeasureUpdateRequest(BaseModel):
    """Partial update, same shape as CategoryUpdateRequest -- every field
    optional so a caller sends only what changed. is_active has its own
    endpoint/audit action below. `dimension`/`conversion_factor_to_base`
    are validated as a pair only when at least one is being changed --
    a request that omits both leaves the existing configuration alone."""

    name: str | None = None
    code: str | None = None
    description: str | None = None
    dimension: str | None = None
    conversion_factor_to_base: Decimal | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value

    @field_validator("code")
    @classmethod
    def _check_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _normalize_code(value)

    @field_validator("dimension")
    @classmethod
    def _strip_dimension(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        return value or None


class UnitOfMeasureStatusChangeRequest(BaseModel):
    is_active: bool
