from pydantic import BaseModel, ConfigDict, field_validator


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    name: str
    code: str | None
    description: str | None
    is_active: bool


class CategoryCreateRequest(BaseModel):
    """organisation_id is never part of this payload -- the endpoint
    always takes it from the authenticated admin (docs/modules/organisation.md #3)."""

    name: str
    code: str | None = None
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
    def _check_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip() or None


class CategoryUpdateRequest(BaseModel):
    """Partial update, same shape as OrganisationUpdateRequest -- every
    field optional so a caller sends only what changed. is_active has
    its own endpoint/audit action below (CategoryStatusChangeRequest),
    since deactivating is a more consequential change than editing
    name/code/description."""

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
        return value.strip() or None


class CategoryStatusChangeRequest(BaseModel):
    is_active: bool
