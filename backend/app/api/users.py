from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import NotFoundError
from app.models.audit_event import ROLE_CHANGED, SECURITY_MODULE
from app.models.user import User
from app.models.user_team import UserTeam
from app.schemas.user import RoleChangeRequest, UserOut
from app.services import audit_service, auth_service, user_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    include_inactive: bool = Query(False),
    team_id: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[UserOut]:
    """Scoped to the caller's own organisation only -- crossing that
    boundary would fail docs/modules/organisation.md #3 and
    docs/modules/users.md acceptance criterion 13. Still ungated for
    reads even though RBAC now exists: it's read-only and never exposes
    password_hash, so it can't be used to escalate privilege; only the
    mutating role/team-membership endpoints are admin-gated.

    team_id doubles as "view team members" (docs/modules/teams.md #6)
    without a separate endpoint -- a team_id from another organisation
    just yields an empty list, since the organisation_id filter below
    still applies. Joins user_teams now that membership is many-to-many
    (docs/modules/roles_rbac.md #1), not a users.team_id column."""
    query = db.query(User).filter(User.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    if team_id is not None:
        query = query.join(UserTeam, UserTeam.user_id == User.id).filter(UserTeam.team_id == team_id)
    users = query.order_by(User.id).offset(skip).limit(limit).all()

    team_map = user_service.team_ids_for_users(db, [u.id for u in users])
    return [user_service.to_user_out(u, team_map[u.id]) for u in users]


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> UserOut:
    user = db.query(User).filter(User.id == user_id, User.organisation_id == current_user.organisation_id).first()
    if user is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's user id.
        raise NotFoundError("User not found.")
    team_ids = user_service.team_ids_for_users(db, [user.id])[user.id]
    return user_service.to_user_out(user, team_ids)


@router.patch("/{user_id}/role", status_code=status.HTTP_204_NO_CONTENT)
def change_user_role(
    user_id: int,
    payload: RoleChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Admin-gated (docs/modules/roles_rbac.md #4), scoped to the admin's
    own organisation -- an Admin from Organisation A cannot change
    Organisation B's users, and a user can never change their own role
    (there's no self-service path here at all). Also revokes the user's
    sessions and records who made the change
    (docs/modules/session_security.md #8/#14, docs/modules/audit_trail.md)."""
    user = db.query(User).filter(User.id == user_id, User.organisation_id == admin.organisation_id).first()
    if user is None:
        raise NotFoundError("User not found.")

    old_role = user.role
    user.role = payload.role
    db.add(user)
    auth_service.revoke_all_sessions(db, user.id)
    audit_service.log_event(
        db,
        action=ROLE_CHANGED,
        module=SECURITY_MODULE,
        organisation_id=admin.organisation_id,
        user_id=user.id,
        actor_user_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        result="success",
        details=f"role: {old_role} -> {payload.role}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
