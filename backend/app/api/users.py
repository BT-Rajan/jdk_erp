from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.core.security import hash_password
from app.core.validation import validate_company_email_domain
from app.models.audit_event import ROLE_CHANGED, SECURITY_MODULE, TEAM_ADDED, USER_CREATED, USER_STATUS_CHANGED
from app.models.notification import INFO
from app.models.organisation import Organisation
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam
from app.schemas.pagination import PaginatedResponse
from app.schemas.user import RoleChangeRequest, UserCreateRequest, UserOut, UserStatusChangeRequest
from app.services import audit_service, auth_service, notification_service, user_service

router = APIRouter(prefix="/api/users", tags=["users"])

# The one place a `sort_by` string becomes a real column
# (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md's list-contract
# follow-up) -- app/core/list_query.apply_sort refuses anything not in
# this map.
_SORT_FIELDS = {
    "full_name": User.full_name,
    "email": User.email,
    "username": User.username,
    "role": User.role,
    "created_at": User.created_at,
}


@router.get("", response_model=PaginatedResponse[UserOut])
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    team_id: int | None = Query(None),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[UserOut]:
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
    (docs/modules/roles_rbac.md #1), not a users.team_id column.

    q (docs/modules/search.md) searches full_name/email/username,
    applied before sort/pagination -- after organisation_id, is_active
    and team_id -- so a keyword can only narrow what this endpoint
    would already return, never widen it. page/sort follow the common
    list contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md)."""
    query = db.query(User).filter(User.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(User.is_active.is_(True))
    if team_id is not None:
        query = query.join(UserTeam, UserTeam.user_id == User.id).filter(UserTeam.team_id == team_id)
    query = apply_keyword_filter(query, q, User.full_name, User.email, User.username)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=User.id)

    users, pagination = paginate(query, page, page_size)
    team_map = user_service.team_ids_for_users(db, [u.id for u in users])
    return PaginatedResponse(
        data=[user_service.to_user_out(u, team_map[u.id]) for u in users], pagination=pagination
    )


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserOut:
    """Admin-gated (docs/modules/roles_rbac.md #4), the one place a User
    row is created outside scripts/seed_admin.py (docs/modules/users.md
    #4/#10 criterion 1). organisation_id always comes from the
    authenticated admin, never the request body (#8, criterion 12).
    Login-identifier uniqueness stays global, not per-organisation, same
    as login itself (docs/modules/users.md's Implementation approach)."""
    organisation = db.query(Organisation).filter(Organisation.id == admin.organisation_id).first()
    try:
        email = validate_company_email_domain(
            payload.email, organisation.email_domain if organisation else None
        )
    except ValueError as exc:
        raise ValidationError(str(exc), fields={"email": str(exc)}) from exc

    if db.query(User).filter((User.email == email) | (User.username == payload.username)).first() is not None:
        # Criterion 5: duplicate login identifier is rejected. One message
        # for either collision -- the field-level distinction isn't worth
        # confirming which of the two another organisation already uses.
        raise ConflictError("A user with this email or username already exists.")

    team_ids = set(payload.team_ids)
    teams: list[Team] = []
    if team_ids:
        teams = (
            db.query(Team)
            .filter(Team.organisation_id == admin.organisation_id, Team.id.in_(team_ids), Team.is_active.is_(True))
            .all()
        )
        found_ids = {team.id for team in teams}
        if found_ids != team_ids:
            # Criterion 6: invalid team assignment is rejected -- an id
            # that doesn't exist, belongs to another organisation, or is
            # inactive all fail the same way as "not a valid team here".
            raise ValidationError("One or more teams are invalid.", fields={"team_ids": "One or more teams are invalid."})

    user = User(
        organisation_id=admin.organisation_id,
        full_name=payload.full_name,
        email=email,
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.flush()  # assigns user.id for the UserTeam rows and audit event below

    for team in teams:
        db.add(UserTeam(user_id=user.id, team_id=team.id))

    audit_service.log_event(
        db,
        action=USER_CREATED,
        module=SECURITY_MODULE,
        organisation_id=admin.organisation_id,
        user_id=user.id,
        actor_user_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        result="success",
        details=f"role: {user.role}",
        ip_address=request.client.host if request.client else None,
    )
    # Audit-trail parity with the standalone add_team_member flow
    # (app/api/teams.py) -- a membership assigned at creation time is
    # exactly as auditable as one assigned afterward, same action/detail
    # shape, not a second event type invented for this call site.
    for team in teams:
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
    # One commit for the whole operation -- the user row, its team
    # memberships and the audit event succeed or fail together
    # (docs/modules/database_transaction_integrity.md #5/#6/#9).
    db.commit()
    db.refresh(user)
    return user_service.to_user_out(user, sorted(team_ids))


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
    Organisation B's users. No non-admin can reach this endpoint at all
    (there's no self-service path here), and an admin can never target
    their own row through it either, mirroring change_user_status below
    -- otherwise an admin could self-demote out of every admin screen,
    or self-promote, with nothing stopping either. Also revokes the
    user's sessions and records who made the change
    (docs/modules/session_security.md #8/#14, docs/modules/audit_trail.md)."""
    user = db.query(User).filter(User.id == user_id, User.organisation_id == admin.organisation_id).first()
    if user is None:
        raise NotFoundError("User not found.")
    if user.id == admin.id:
        raise BusinessRuleError("You cannot change your own role.")

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
    # An "important status change" (docs/modules/notifications.md #8) --
    # one of this module's two proof-of-concept call sites. No email by
    # default (#8's spam guidance applies doubly to email).
    notification_service.notify(
        db,
        user,
        type=INFO,
        title="Your role was changed",
        message=f"Your role is now {payload.role}.",
        entity_type="user",
        entity_id=user.id,
    )
    db.commit()


@router.patch("/{user_id}/status", status_code=status.HTTP_204_NO_CONTENT)
def change_user_status(
    user_id: int,
    payload: UserStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Admin-gated, org-scoped, mirrors change_user_role above
    (docs/modules/users.md #6/#10 criterion 7 -- activate/deactivate).
    Deactivating also revokes sessions (docs/modules/session_security.md
    #8) so an already-issued access token stops working on its next use,
    same as a deactivated organisation already does (app/api/deps.py).
    An admin can never deactivate their own account through this
    endpoint -- there'd be no one left to undo it."""
    user = db.query(User).filter(User.id == user_id, User.organisation_id == admin.organisation_id).first()
    if user is None:
        raise NotFoundError("User not found.")
    if user.id == admin.id and not payload.is_active:
        raise BusinessRuleError("You cannot deactivate your own account.")

    user.is_active = payload.is_active
    db.add(user)
    if not payload.is_active:
        auth_service.revoke_all_sessions(db, user.id)
    audit_service.log_event(
        db,
        action=USER_STATUS_CHANGED,
        module=SECURITY_MODULE,
        organisation_id=admin.organisation_id,
        user_id=user.id,
        actor_user_id=admin.id,
        entity_type="user",
        entity_id=user.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
