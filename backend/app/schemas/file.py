from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organisation_id: int
    original_filename: str
    mime_type: str
    size_bytes: int
    entity_type: str | None
    entity_id: int | None
    uploaded_by_user_id: int | None
    status: str
    created_at: datetime
