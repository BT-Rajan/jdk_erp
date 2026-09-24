from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.id_formats import CATEGORY_CODE
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import (
    CATEGORY_CREATED,
    CATEGORY_STATUS_CHANGED,
    CATEGORY_UPDATED,
    MASTER_DATA_MODULE,
)
from app.models.category import Category
from app.models.product import Product
from app.models.raw_material import RawMaterial
from app.models.user import User
from app.schemas.category import (
    CategoryCreateRequest,
    CategoryOut,
    CategoryStatusChangeRequest,
    CategoryUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service

router = APIRouter(prefix="/api/categories", tags=["categories"])

# See app/api/users.py's _SORT_FIELDS for the reasoning.
_SORT_FIELDS = {
    "name": Category.name,
    "code": Category.code,
    "applies_to": Category.applies_to,
    "created_at": Category.created_at,
}

_MAX_CODE_ATTEMPTS = 5


def _generate_category_code(db: Session, organisation_id: int) -> str:
    existing = db.query(Category).filter(Category.organisation_id == organisation_id).count()
    return CATEGORY_CODE.format(existing + 1)


def _in_use(db: Session, category: Category) -> bool:
    return (
        db.query(Product.id).filter(Product.category_id == category.id).first() is not None
        or db.query(RawMaterial.id).filter(RawMaterial.category_id == category.id).first() is not None
    )


def _get_category_in_org(db: Session, category_id: int, organisation_id: int) -> Category:
    category = (
        db.query(Category)
        .filter(Category.id == category_id, Category.organisation_id == organisation_id)
        .first()
    )
    if category is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's category id
        # (docs/modules/organisation.md #3).
        raise NotFoundError("Category not found.")
    return category


@router.get("", response_model=PaginatedResponse[CategoryOut])
def list_categories(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    applies_to: Literal["product", "raw_material"] | None = Query(None),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[CategoryOut]:
    """Scoped to the caller's own organisation only (docs/modules/categories.md #4).
    Open to any authenticated organisation member, same as Teams/Users --
    it's read-only reference data every module that assigns a category
    needs to look up, not a privileged action. q searches name/code,
    applied after the organisation/is_active filters -- narrows this same
    query, never a separate lookup. page/sort follow the common list
    contract (docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md)."""
    query = db.query(Category).filter(Category.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(Category.is_active.is_(True))
    if applies_to:
        query = query.filter(Category.applies_to == applies_to)
    query = apply_keyword_filter(query, q, Category.name, Category.code)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=Category.id)

    categories, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[CategoryOut.model_validate(c) for c in categories], pagination=pagination)


@router.get("/{category_id}", response_model=CategoryOut)
def get_category(
    category_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Category:
    return _get_category_in_org(db, category_id, current_user.organisation_id)


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Category:
    """Admin-gated (docs/modules/categories.md #5), the same RBAC gate
    Teams/Users mutations already use -- no category-specific
    authorization layer. organisation_id always comes from the
    authenticated admin, never the request body. `code` is system-
    generated and retried against a collision the same way Supplier/
    Customer already do (docs/modules/categories.md #4)."""
    category: Category | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = _generate_category_code(db, admin.organisation_id)
        category = Category(
            organisation_id=admin.organisation_id,
            name=payload.name,
            code=code,
            applies_to=payload.applies_to,
            description=payload.description,
        )
        db.add(category)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or category is None:
        raise ConflictError(
            "A category with this name already exists, or a unique code could not be generated."
        ) from last_error

    audit_service.log_event(
        db,
        action=CATEGORY_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="category",
        entity_id=category.id,
        result="success",
        details=f"name: {category.name}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(category)
    return category


@router.patch("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: int,
    payload: CategoryUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Category:
    """Admin-gated partial update, same shape as
    PATCH /api/organisations/me. is_active is deliberately not editable
    here -- see change_category_status below."""
    category = _get_category_in_org(db, category_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    if updates.get("applies_to") is None:
        updates.pop("applies_to", None)
    elif updates["applies_to"] != category.applies_to and _in_use(db, category):
        raise BusinessRuleError(
            "This category is already used by products or raw materials, so its type can't change.",
            fields={"applies_to": "Already in use."},
        )
    before = {field: getattr(category, field) for field in updates}
    for field, value in updates.items():
        setattr(category, field, value)
    db.add(category)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A category with this name or code already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=CATEGORY_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="category",
            entity_id=category.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(category)
    return category


@router.patch("/{category_id}/status", response_model=CategoryOut)
def change_category_status(
    category_id: int,
    payload: CategoryStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Category:
    """Admin-gated activate/deactivate (docs/modules/categories.md #6).
    No self-lockout concern here (unlike a user or an organisation
    deactivating themselves) -- deactivating a category only affects
    whether it can be picked for new records, never anyone's ability to
    sign in or use the system."""
    category = _get_category_in_org(db, category_id, admin.organisation_id)
    category.is_active = payload.is_active
    db.add(category)

    audit_service.log_event(
        db,
        action=CATEGORY_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="category",
        entity_id=category.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(category)
    return category
