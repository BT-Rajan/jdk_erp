from pydantic import BaseModel, ConfigDict, field_validator


class UnitOfMeasureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    name: str
    code: str
    description: str | None
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


class UnitOfMeasureCreateRequest(BaseModel):
    """organisation_id is never part of this payload -- the endpoint
    always takes it from the authenticated admin (docs/modules/organisation.md #3)."""

    name: str
    code: str
    description: str | None = None

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


class UnitOfMeasureUpdateRequest(BaseModel):
    """Partial update, same shape as CategoryUpdateRequest -- every field
    optional so a caller sends only what changed. is_active has its own
    endpoint/audit action below."""

    name: str | None = None
    code: str | None = None
    description: str | None = None

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


class UnitOfMeasureStatusChangeRequest(BaseModel):
    is_active: bool
