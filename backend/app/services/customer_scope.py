from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Query, Session

from app.core.errors import NotFoundError
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


# --- Sales record scope (Sales S2) ----------------------------------------
#
# Every Sales record (quotation, order, ...) belongs to exactly one
# Customer and inherits that Customer's visibility: Sales record ->
# Customer -> assigned_to_user_id -> the caller's resolved scope above.
# There is deliberately no separate Sales ownership column or permission
# key -- a Sales endpoint reuses the two helpers below and nothing else.


def get_accessible_customer(db: Session, user: User, customer_id: int) -> Customer:
    """The one object-level check for "may this caller act on this
    customer" -- for reading a customer, and for any Sales create/update
    that names a customer_id. A customer in another organisation, or one
    outside the caller's scope, is the same 404 as one that doesn't
    exist, so an id guessed from a URL confirms nothing."""
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.organisation_id == user.organisation_id)
        .first()
    )
    if customer is None or not can_view_customer(db, user, customer):
        raise NotFoundError("Customer not found.")
    return customer


def scope_by_customer(db: Session, user: User, query: Query, customer_id_column) -> Query:
    """Restricts any customer-linked query (a Sales list, or a single-
    record lookup before a read/update/delete) to rows whose customer is
    in the caller's organisation and scope. Applied server-side to the
    query itself, so a filter or id in the request can only narrow what
    the caller could already see."""
    visible = select(Customer.id).where(Customer.organisation_id == user.organisation_id)
    visibility_filter = visible_customer_filter(db, user)
    if visibility_filter is not None:
        visible = visible.where(visibility_filter)
    return query.filter(customer_id_column.in_(visible))


# --- Customer reassignment (Department Head) -------------------------------


def _share_a_team(db: Session, user_ids: set[int]) -> bool:
    """True when one team contains every user in `user_ids`."""
    rows = db.query(UserTeam.team_id, UserTeam.user_id).filter(UserTeam.user_id.in_(user_ids)).all()
    members_by_team: dict[int, set[int]] = {}
    for team_id, user_id in rows:
        members_by_team.setdefault(team_id, set()).add(user_id)
    return any(members >= user_ids for members in members_by_team.values())


def can_reassign_customer(db: Session, user: User, customer: Customer, new_assignee_id: int | None) -> bool:
    """Department Head authority, per the existing department/role model
    (docs/modules/teams.md #4: Role = Manager + Team = X means this user
    heads team X). Admin/super_admin may reassign any customer in their
    organisation. A manager may move a customer only within a department
    they head: one team must contain the manager, the customer's current
    owner and the new owner. Anyone else -- including a manager acting
    outside their own team, or on an unassigned customer, or un-assigning
    one -- is refused. Only the customer's current ownership pointer
    changes; nothing historical is rewritten."""
    if user.role in ADMIN_ROLES:
        return True
    if user.role != MANAGER or customer.assigned_to_user_id is None or new_assignee_id is None:
        return False
    return _share_a_team(db, {user.id, customer.assigned_to_user_id, new_assignee_id})


def can_assign_new_customer(db: Session, user: User, assignee_id: int | None) -> bool:
    """The same Department Head boundary applied to a customer's first
    owner at creation: admin -> anyone; manager -> themselves, nobody,
    or a member of a team they head; everyone else is always assigned to
    themselves by the caller before this is reached."""
    if user.role in ADMIN_ROLES or assignee_id is None or assignee_id == user.id:
        return True
    if user.role != MANAGER:
        return False
    return _share_a_team(db, {user.id, assignee_id})


def is_team_head_of(db: Session, user: User, owner_user_id: int | None) -> bool:
    """True when `user` is a manager on a team the owner also belongs to --
    the same Department Head notion reassignment uses (S2). Used for
    rejecting a quotation (S12.1)."""
    if user.role != MANAGER or owner_user_id is None:
        return False
    return _share_a_team(db, {user.id, owner_user_id})
