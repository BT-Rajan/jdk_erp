from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    include_inactive: bool = Query(False),
    team_id: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[User]:
    """Scoped to the caller's own organisation only -- crossing that
    boundary would fail docs/modules/organisation.md #3 and
    docs/modules/users.md acceptance criterion 13. No role check yet
    (RBAC doesn't exist): this is read-only and never exposes
    password_hash, so it can't be used to escalate privilege.

    team_id doubles as "view team members" (docs/modules/teams.md #6)
    without a separate endpoint -- a team_id from another organisation
    just yields an empty list, since the organisation_id filter below
    still applies."""
    query = db.query(User).filter(User.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    if team_id is not None:
        query = query.filter(User.team_id == team_id)
    return query.order_by(User.id).offset(skip).limit(limit).all()


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
    user = db.query(User).filter(User.id == user_id, User.organisation_id == current_user.organisation_id).first()
    if user is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's user id.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user
