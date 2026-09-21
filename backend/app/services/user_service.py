from sqlalchemy.orm import Session

from app.models.user import User
from app.models.user_team import UserTeam
from app.schemas.user import UserOut


def team_ids_for_users(db: Session, user_ids: list[int]) -> dict[int, list[int]]:
    """Batch-fetches team memberships for several users in one query,
    rather than one query per user (docs/modules/users.md #9)."""
    result: dict[int, list[int]] = {user_id: [] for user_id in user_ids}
    if not user_ids:
        return result
    rows = db.query(UserTeam.user_id, UserTeam.team_id).filter(UserTeam.user_id.in_(user_ids)).all()
    for user_id, team_id in rows:
        result[user_id].append(team_id)
    return result


def to_user_out(user: User, team_ids: list[int]) -> UserOut:
    """The one place a User row becomes the public UserOut shape --
    shared by GET /api/auth/me and the GET /api/users directory endpoints
    (docs/modules/users.md #2/#8)."""
    return UserOut(
        id=user.id,
        organisation_id=user.organisation_id,
        full_name=user.full_name,
        email=user.email,
        username=user.username,
        is_active=user.is_active,
        last_login_at=user.last_login_at,
        role=user.role,
        team_ids=sorted(team_ids),
    )
