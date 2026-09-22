from sqlalchemy import ColumnElement
from sqlalchemy.orm import Session

from app.core.roles import ADMIN_ROLES, MANAGER, TEAM_MEMBER
from app.core.scopes import ALL, OWN, TEAM
from app.models.customer import Customer
from app.models.user import User
from app.models.user_team import UserTeam
from app.services import authorization_service

_MODULE_KEY = "customers"
_VIEW_ACTION = "view"

# docs/modules/permissions.md #4's own role-default table (Super
# Admin/Admin -> ALL, Manager -> TEAM, Team Member -> OWN) -- applied
# only as a fallback when no explicit role_permissions/user_permissions
# row exists for this organisation, so an admin can still override any
# individual user's scope via the existing permissions API
# (docs/modules/permissions.md #5/#6); this never overrides an explicit
# grant, it only fills the gap before one is configured.
_DEFAULT_SCOPE_BY_ROLE = {MANAGER: TEAM, TEAM_MEMBER: OWN}


def resolve_view_scope(db: Session, user: User) -> str:
    """The one place a caller's Customer view scope is resolved
    (docs/modules/customers.md #4) -- admin/super_admin always get ALL,
    the same unconditional bypass every other admin-gated mutation in
    this app already uses (no permission-table lookup needed for a role
    that already bypasses require_admin everywhere else). Everyone else
    goes through the real, already-built scope-resolution engine
    (docs/audit/CUSTOMERS_AUDIT.md's account of what already exists)."""
    if user.role in ADMIN_ROLES:
        return ALL
    explicit = authorization_service.get_effective_scope(db, user, _MODULE_KEY, _VIEW_ACTION)
    if explicit is not None:
        return explicit
    return _DEFAULT_SCOPE_BY_ROLE.get(user.role, OWN)


def visible_customer_filter(db: Session, user: User) -> ColumnElement[bool] | None:
    """A filter condition for `Customer.organisation_id`-scoped query,
    narrowing it by ownership per the caller's resolved scope. None
    means "no further narrowing" (ALL scope) -- the caller applies it
    only when not None, same shape as every other optional filter in
    app/core/list_query.py's callers."""
    scope = resolve_view_scope(db, user)
    if scope == ALL:
        return None
    if scope == TEAM:
        team_ids = authorization_service.get_user_team_ids(db, user)
        if not team_ids:
            # On no team at all, TEAM scope degrades to seeing only
            # their own -- there is no team to derive colleagues from,
            # and returning everything would silently grant ALL.
            return Customer.assigned_to_user_id == user.id
        teammate_ids = (
            db.query(User.id)
            .join(UserTeam, UserTeam.user_id == User.id)
            .filter(UserTeam.team_id.in_(team_ids), User.organisation_id == user.organisation_id)
            .distinct()
        )
        return Customer.assigned_to_user_id.in_(teammate_ids)
    # OWN
    return Customer.assigned_to_user_id == user.id


def can_view_customer(db: Session, user: User, customer: Customer) -> bool:
    """Per-record check for GET /api/customers/{id} and any other
    single-record read -- same scope resolution as the list filter,
    applied to one row instead of a WHERE clause."""
    scope = resolve_view_scope(db, user)
    if scope == ALL:
        return True
    if scope == TEAM:
        team_ids = set(authorization_service.get_user_team_ids(db, user))
        if not team_ids or customer.assigned_to_user_id is None:
            return customer.assigned_to_user_id == user.id
        assignee_team_ids = {
            row[0]
            for row in db.query(UserTeam.team_id).filter(UserTeam.user_id == customer.assigned_to_user_id).all()
        }
        return bool(team_ids & assignee_team_ids)
    return customer.assigned_to_user_id == user.id
