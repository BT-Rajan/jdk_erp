from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.user import User
from app.schemas.notification import NotificationOut, UnreadCountOut
from app.services import notification_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NotificationOut]:
    """No admin/role gate -- a user's own notifications are exactly
    that, their own (docs/modules/notifications.md #4). There is no
    parameter that could widen this to another user's notifications;
    the recipient is always the authenticated caller."""
    return notification_service.list_for_user(db, current_user, unread_only=unread_only, skip=skip, limit=limit)


@router.get("/unread-count", response_model=UnreadCountOut)
def get_unread_count(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return {"count": notification_service.unread_count(db, current_user)}


@router.patch("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_notification_read(
    notification_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    row = notification_service.mark_read(db, current_user, notification_id)
    if row is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # user -- never confirm another user's notification id exists.
        raise NotFoundError("Notification not found.")
    db.commit()


@router.post("/mark-all-read", status_code=status.HTTP_204_NO_CONTENT)
def mark_all_notifications_read(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    notification_service.mark_all_read(db, current_user)
    db.commit()
