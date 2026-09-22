from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NotificationOut(BaseModel):
    """No organisation_id/recipient_user_id -- irrelevant to the client
    that's always looking at its own (UserOut's "never password_hash"
    minimalism, applied here)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    message: str
    entity_type: str | None
    entity_id: int | None
    target_url: str | None
    is_read: bool
    created_at: datetime
    read_at: datetime | None


class UnreadCountOut(BaseModel):
    count: int
