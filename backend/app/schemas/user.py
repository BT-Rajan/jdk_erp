from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserOut(BaseModel):
    """The one public-safe representation of a user -- never includes
    password_hash. Shared by GET /api/auth/me and the GET /api/users
    directory endpoints instead of each defining its own shape
    (docs/modules/users.md #2/#8)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    full_name: str
    email: EmailStr
    username: str
    is_active: bool
    last_login_at: datetime | None
    team_id: int | None
