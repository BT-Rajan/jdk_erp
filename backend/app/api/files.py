from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session
from starlette.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.storage import default_storage
from app.models.user import User
from app.schemas.file import FileOut
from app.services import file_service

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("", response_model=FileOut, status_code=status.HTTP_201_CREATED)
def upload_file(
    upload: UploadFile = File(...),
    entity_type: str | None = Form(None),
    entity_id: int | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileOut:
    """Server-side validation only (docs/modules/file_storage.md #4) --
    upload.content_type (client-supplied) is never trusted; extension
    and content signature are checked in app/services/file_service.py."""
    record = file_service.upload_file(
        db,
        organisation_id=current_user.organisation_id,
        uploaded_by_user_id=current_user.id,
        filename=upload.filename or "",
        stream=upload.file,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    return FileOut.model_validate(record)


@router.get("/{file_id}")
def download_file(
    file_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> StreamingResponse:
    """authenticate (get_current_user) -> authorize -> locate -> stream
    -> content type (docs/modules/file_storage.md #6) -- the physical
    storage_key never appears in the response."""
    record = file_service.get_file_or_404(db, file_id, current_user.organisation_id)
    file_service.authorize_file_access(db, current_user, record)
    return StreamingResponse(
        default_storage.download(record.storage_key),
        media_type=record.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{record.original_filename}"'},
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    """Logical removal only (docs/modules/file_storage.md #8) -- see
    app/services/file_service.soft_delete_file."""
    record = file_service.get_file_or_404(db, file_id, current_user.organisation_id)
    file_service.authorize_file_access(db, current_user, record)
    file_service.soft_delete_file(db, record)
