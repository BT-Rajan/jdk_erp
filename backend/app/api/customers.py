from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import AccessDeniedError, ConflictError, NotFoundError, ValidationError
from app.core.id_formats import CUSTOMER_ID
from app.core.list_query import apply_sort, paginate
from app.core.roles import ADMIN_ROLES, MANAGER, TEAM_MEMBER
from app.core.search import apply_keyword_filter
from app.models.audit_event import (
    CUSTOMER_ASSIGNED,
    CUSTOMER_CREATED,
    CUSTOMER_STATUS_CHANGED,
    CUSTOMER_UPDATED,
    MASTER_DATA_MODULE,
)
from app.models.customer import Customer
from app.models.user import User
from app.schemas.customer import (
    CustomerAssignRequest,
    CustomerCreateRequest,
    CustomerOut,
    CustomerStatusChangeRequest,
    CustomerUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service, customer_scope

router = APIRouter(prefix="/api/customers", tags=["customers"])

# See app/api/users.py's _SORT_FIELDS for the reasoning.
_SORT_FIELDS = {
    "code": Customer.code,
    "name": Customer.name,
    "created_at": Customer.created_at,
}

_MAX_CODE_ATTEMPTS = 5


def _require_can_assign(user: User = Depends(get_current_user)) -> User:
    """Reassignment is deliberately narrower than general view access
    (docs/modules/customers.md #3/#4) -- a team_member can create and
    view their own customers but never reassign one, mirroring
    jdk_clean's real is_admin-or-department_head gate
    (docs/audit/CUSTOMERS_AUDIT.md) rather than routing this one
    business rule through the generic scope engine."""
    if user.role not in ADMIN_ROLES and user.role != MANAGER:
        raise AccessDeniedError("Only an admin or manager can assign customers.")
    return user


def _get_customer_in_org(db: Session, customer_id: int, organisation_id: int) -> Customer:
    customer = (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.organisation_id == organisation_id)
        .first()
    )
    if customer is None:
        raise NotFoundError("Customer not found.")
    return customer


def _get_visible_customer(db: Session, customer_id: int, current_user: User) -> Customer:
    """404, not 403, for a customer that exists but is out of the
    caller's view scope -- same reasoning as a cross-organisation id
    (never confirm a record's existence to a caller who can't see it),
    directly adopted from jdk_clean's own real, deliberate choice here
    (docs/audit/CUSTOMERS_AUDIT.md)."""
    customer = _get_customer_in_org(db, customer_id, current_user.organisation_id)
    if not customer_scope.can_view_customer(db, current_user, customer):
        raise NotFoundError("Customer not found.")
    return customer


def _generate_customer_code(db: Session, organisation_id: int) -> str:
    existing = db.query(Customer).filter(Customer.organisation_id == organisation_id).count()
    return CUSTOMER_ID.format(existing + 1)


@router.get("", response_model=PaginatedResponse[CustomerOut])
def list_customers(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[CustomerOut]:
    """Scoped to the caller's own organisation, then further narrowed by
    their resolved OWN/TEAM/ALL view scope (docs/modules/customers.md #4)
    -- the one place this module differs from Categories/Units, which
    have no ownership dimension at all. q searches
    name/code/contact_person/phone, applied after every scope filter, so
    a keyword can only narrow what this caller could already see."""
    query = db.query(Customer).filter(Customer.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(Customer.is_active.is_(True))
    visibility_filter = customer_scope.visible_customer_filter(db, current_user)
    if visibility_filter is not None:
        query = query.filter(visibility_filter)
    query = apply_keyword_filter(query, q, Customer.name, Customer.code, Customer.contact_person, Customer.phone)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=Customer.id)

    customers, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[CustomerOut.model_validate(c) for c in customers], pagination=pagination)


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Customer:
    return _get_visible_customer(db, customer_id, current_user)


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Customer:
    """Open to any authenticated organisation member, not admin-gated --
    onboarding a new customer is ordinary sales work, not a master-data
    administration action (docs/modules/customers.md #5, matching
    jdk_clean's own real behaviour per docs/audit/CUSTOMERS_AUDIT.md). A
    team_member's new customer is always auto-assigned to themselves,
    silently overriding whatever assigned_to_user_id they sent -- they
    can create their own customers but can never assign one to someone
    else (that would be a privilege-escalation path around
    _require_can_assign below). A manager/admin may specify any active
    user in their own organisation, or leave it unassigned."""
    assigned_to_user_id = payload.assigned_to_user_id
    if current_user.role == TEAM_MEMBER:
        assigned_to_user_id = current_user.id
    elif assigned_to_user_id is not None:
        assignee = (
            db.query(User)
            .filter(
                User.id == assigned_to_user_id,
                User.organisation_id == current_user.organisation_id,
                User.is_active.is_(True),
            )
            .first()
        )
        if assignee is None:
            raise ValidationError(
                "assigned_to_user_id must be an active user in your organisation.",
                fields={"assigned_to_user_id": "Not a valid user in your organisation."},
            )

    if payload.phone is not None:
        duplicate = (
            db.query(Customer)
            .filter(Customer.organisation_id == current_user.organisation_id, Customer.phone == payload.phone)
            .first()
        )
        if duplicate is not None:
            raise ConflictError("A customer with this phone number already exists.")

    customer: Customer | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = _generate_customer_code(db, current_user.organisation_id)
        customer = Customer(
            organisation_id=current_user.organisation_id,
            code=code,
            name=payload.name,
            contact_person=payload.contact_person,
            phone=payload.phone,
            email=payload.email,
            address=payload.address,
            assigned_to_user_id=assigned_to_user_id,
        )
        db.add(customer)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or customer is None:
        raise ConflictError("Could not generate a unique customer code. Please try again.") from last_error

    audit_service.log_event(
        db,
        action=CUSTOMER_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="customer",
        entity_id=customer.id,
        result="success",
        details=f"code: {customer.code}, name: {customer.name}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(customer)
    return customer


@router.patch("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int,
    payload: CustomerUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Customer:
    """Admin-gated, same shape as PATCH /api/categories/{id} -- mirrors
    jdk_clean's own real (and deliberately strict) choice that editing an
    existing customer master record, unlike creating one, is an admin
    action (docs/audit/CUSTOMERS_AUDIT.md). is_active and
    assigned_to_user_id each have their own endpoint below."""
    customer = _get_customer_in_org(db, customer_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    before = {field: getattr(customer, field) for field in updates}
    for field, value in updates.items():
        setattr(customer, field, value)
    db.add(customer)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A customer with this phone number already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=CUSTOMER_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="customer",
            entity_id=customer.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(customer)
    return customer


@router.patch("/{customer_id}/status", response_model=CustomerOut)
def change_customer_status(
    customer_id: int,
    payload: CustomerStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Customer:
    """Admin-gated activate/deactivate (docs/modules/customers.md #8)."""
    customer = _get_customer_in_org(db, customer_id, admin.organisation_id)
    customer.is_active = payload.is_active
    db.add(customer)

    audit_service.log_event(
        db,
        action=CUSTOMER_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="customer",
        entity_id=customer.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(customer)
    return customer


@router.patch("/{customer_id}/assign", response_model=CustomerOut)
def assign_customer(
    customer_id: int,
    payload: CustomerAssignRequest,
    request: Request,
    user: User = Depends(_require_can_assign),
    db: Session = Depends(get_db),
) -> Customer:
    """Admin-or-manager-gated (docs/modules/customers.md #3) -- a
    team_member can never reassign a customer, including their own.
    `assigned_to_user_id: null` explicitly un-assigns."""
    customer = _get_customer_in_org(db, customer_id, user.organisation_id)

    if payload.assigned_to_user_id is not None:
        assignee = (
            db.query(User)
            .filter(
                User.id == payload.assigned_to_user_id,
                User.organisation_id == user.organisation_id,
                User.is_active.is_(True),
            )
            .first()
        )
        if assignee is None:
            raise ValidationError(
                "assigned_to_user_id must be an active user in your organisation.",
                fields={"assigned_to_user_id": "Not a valid user in your organisation."},
            )

    old_assignee = customer.assigned_to_user_id
    customer.assigned_to_user_id = payload.assigned_to_user_id
    db.add(customer)

    audit_service.log_event(
        db,
        action=CUSTOMER_ASSIGNED,
        module=MASTER_DATA_MODULE,
        organisation_id=user.organisation_id,
        actor_user_id=user.id,
        entity_type="customer",
        entity_id=customer.id,
        result="success",
        details=f"assigned_to_user_id: {old_assignee} -> {payload.assigned_to_user_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(customer)
    return customer
