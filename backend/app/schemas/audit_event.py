from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int | None
    action: str
    module: str
    user_id: int | None
    actor_user_id: int | None
    entity_type: str | None
    entity_id: int | None
    result: str | None
    reason: str | None
    details: str | None
    username_attempted: str | None
    ip_address: str | None
    created_at: datetime
