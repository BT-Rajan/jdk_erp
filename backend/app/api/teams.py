from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models.audit_event import SECURITY_MODULE, TEAM_ADDED, TEAM_REMOVED
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam
from app.schemas.team import TeamMemberIn, TeamOut
from app.services import audit_service

router = APIRouter(prefix="/api/teams", tags=["teams"])


def _get_team_in_org(db: Session, team_id: int, organisation_id: int) -> Team:
    team = db.query(Team).filter(Team.id == team_id, Team.organisation_id == organisation_id).first()
    if team is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's team id.
        raise NotFoundError("Team not found.")
    return team


@router.get("", response_model=list[TeamOut])
def list_teams(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Team]:
    """Scoped to the caller's own organisation only (docs/modules/teams.md #9)."""
    query = db.query(Team).filter(Team.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(Team.is_active.is_(True))
    return query.order_by(Team.id).offset(skip).limit(limit).all()


@router.get("/{team_id}", response_model=TeamOut)
def get_team(team_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Team:
    return _get_team_in_org(db, team_id, current_user.organisation_id)


@router.post("/{team_id}/members", status_code=status.HTTP_204_NO_CONTENT)
def add_team_member(
    team_id: int,
    payload: TeamMemberIn,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Admin-gated (docs/modules/roles_rbac.md #4): a user cannot add
    themselves, or anyone else, to a team. Both the team and the user
    must belong to the admin's own organisation (docs/modules/teams.md #9)."""
    team = _get_team_in_org(db, team_id, admin.organisation_id)
    if not team.is_active:
        # docs/modules/teams.md #7 acceptance criterion: an inactive team
        # cannot receive new users.
        raise BusinessRuleError("Cannot add a member to an inactive team.")

    user = db.query(User).filter(User.id == payload.user_id, User.organisation_id == admin.organisation_id).first()
    if user is None:
        raise NotFoundError("User not found.")

    existing = db.query(UserTeam).filter(UserTeam.user_id == user.id, UserTeam.team_id == team.id).first()
    if existing is not None:
        raise ConflictError("User is already a member of this team.")

    db.add(UserTeam(user_id=user.id, team_id=team.id))
    audit_service.log_event(
        db,
        action=TEAM_ADDED,
        module=SECURITY_MODULE,
        organisation_id=admin.organisation_id,
        user_id=user.id,
        actor_user_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        result="success",
        details=f"team: {team.name} (id={team.id})",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()


@router.delete("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_team_member(
    team_id: int,
    user_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Admin-gated, same organisation-boundary check as adding a member."""
    team = _get_team_in_org(db, team_id, admin.organisation_id)

    membership = db.query(UserTeam).filter(UserTeam.user_id == user_id, UserTeam.team_id == team.id).first()
    if membership is None:
        raise NotFoundError("Membership not found.")

    db.delete(membership)
    audit_service.log_event(
        db,
        action=TEAM_REMOVED,
        module=SECURITY_MODULE,
        organisation_id=admin.organisation_id,
        user_id=user_id,
        actor_user_id=admin.id,
        entity_type="user",
        entity_id=user_id,
        result="success",
        details=f"team: {team.name} (id={team.id})",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
