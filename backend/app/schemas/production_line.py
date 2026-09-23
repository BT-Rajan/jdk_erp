from pydantic import BaseModel, ConfigDict, field_validator


class ProductionLineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    code: str
    name: str
    is_active: bool


class ProductionLineCreateRequest(BaseModel):
    code: str
    name: str

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


class ProductionLineUpdateRequest(BaseModel):
    """Partial update, same shape as every other master. `code` is
    deliberately absent -- immutable after creation, the same treatment
    already given to Product/RawMaterial's manually-assigned codes."""

    name: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return value


class ProductionLineStatusChangeRequest(BaseModel):
    is_active: bool
