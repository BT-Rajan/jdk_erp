from sqlalchemy.orm import Session

from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_permission import UserPermission
from app.models.user_team import UserTeam


def get_effective_scope(db: Session, user: User, module_key: str, action: str) -> str | None:
    """The `can(user, action, resource)` concept from
    docs/modules/permissions.md #11, minus the resource argument -- no
    concrete resource type exists yet, so this answers "is this allowed,
    at what scope" for a module+action. A user-specific override
    (docs/modules/permissions.md #5/#6) always wins over the role
    default; no grant at all means deny (returns None)."""
    user_permission = (
        db.query(UserPermission)
        .filter(
            UserPermission.user_id == user.id,
            UserPermission.module_key == module_key,
            UserPermission.action == action,
        )
        .first()
    )
    if user_permission is not None:
        return user_permission.scope

    role_permission = (
        db.query(RolePermission)
        .filter(
            RolePermission.organisation_id == user.organisation_id,
            RolePermission.role == user.role,
            RolePermission.module_key == module_key,
            RolePermission.action == action,
        )
        .first()
    )
    return role_permission.scope if role_permission is not None else None


def can(db: Session, user: User, module_key: str, action: str) -> bool:
    return get_effective_scope(db, user, module_key, action) is not None


def get_user_team_ids(db: Session, user: User) -> list[int]:
    """The one shared "which teams can I see" building block every future
    module's TEAM-scope query filters against
    (docs/modules/permissions.md #12's `WHERE ... team_id IN (...)`)."""
    return [row[0] for row in db.query(UserTeam.team_id).filter(UserTeam.user_id == user.id).all()]
