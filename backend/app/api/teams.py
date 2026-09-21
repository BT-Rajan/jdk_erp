from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.team import Team
from app.models.user import User
from app.schemas.team import TeamOut

router = APIRouter(prefix="/api/teams", tags=["teams"])


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
    team = db.query(Team).filter(Team.id == team_id, Team.organisation_id == current_user.organisation_id).first()
    if team is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's team id.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found.")
    return team
