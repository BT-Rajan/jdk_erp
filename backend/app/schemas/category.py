from pydantic import BaseModel, ConfigDict, field_validator

from app.core.validation import check_max_length


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    name: str
    code: str
    description: str | None
    is_active: bool


class CategoryCreateRequest(BaseModel):
    """organisation_id and code are never part of this payload -- the
    endpoint always takes organisation from the authenticated admin
    (docs/modules/organisation.md #3) and generates code server-side
    (docs/modules/categories.md #4), same as every other Phase 2 master."""

    name: str
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return check_max_length(value, 80, "Name")


class CategoryUpdateRequest(BaseModel):
    """Partial update. `code` is immutable -- absent here, same as every
    other master. is_active has its own endpoint/audit action below
    (CategoryStatusChangeRequest), since deactivating is a more
    consequential change than editing name/description."""

    name: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Name is required.")
        return check_max_length(value, 80, "Name")


class CategoryStatusChangeRequest(BaseModel):
    is_active: bool
