from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.core.roles import VALID_ROLES
from app.core.validation import validate_password_complexity


class UserOut(BaseModel):
    """The one public-safe representation of a user -- never includes
    password_hash. Shared by GET /api/auth/me and the GET /api/users
    directory endpoints instead of each defining its own shape
    (docs/modules/users.md #2/#8). team_ids is a list, not a single value
    -- docs/modules/roles_rbac.md #1, a user can belong to several teams."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    full_name: str
    email: EmailStr
    username: str
    is_active: bool
    last_login_at: datetime | None
    role: str
    team_ids: list[int]


class RoleChangeRequest(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def _check_valid_role(cls, value: str) -> str:
        if value not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        return value


class UserCreateRequest(BaseModel):
    """docs/modules/users.md #4/#10 -- an authorised administrator creates
    a user, assigns a role, and optionally assigns team(s) up front.
    organisation_id is never part of this payload (#8): the endpoint
    always takes it from the authenticated admin."""

    full_name: str
    email: EmailStr
    username: str
    password: str
    role: str
    team_ids: list[int] = []

    @field_validator("full_name")
    @classmethod
    def _check_full_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Full name is required.")
        return value

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Username is required.")
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return validate_password_complexity(value)

    @field_validator("role")
    @classmethod
    def _check_role(cls, value: str) -> str:
        if value not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}")
        return value


class UserStatusChangeRequest(BaseModel):
    is_active: bool
