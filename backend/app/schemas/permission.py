from pydantic import BaseModel, ConfigDict, field_validator

from app.core.scopes import VALID_SCOPES


class PermissionScopeIn(BaseModel):
    scope: str

    @field_validator("scope")
    @classmethod
    def _check_scope(cls, value: str) -> str:
        if value not in VALID_SCOPES:
            raise ValueError(f"scope must be one of {sorted(VALID_SCOPES)}")
        return value


class RolePermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: str
    module_key: str
    action: str
    scope: str


class UserPermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    module_key: str
    action: str
    scope: str


class EffectiveScopeOut(BaseModel):
    module_key: str
    action: str
    scope: str | None
