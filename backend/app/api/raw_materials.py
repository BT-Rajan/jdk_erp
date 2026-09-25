from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.id_formats import RAW_MATERIAL_CODE
from app.core.list_query import apply_sort, paginate
from app.core.search import apply_keyword_filter
from app.models.audit_event import (
    MASTER_DATA_MODULE,
    RAW_MATERIAL_CREATED,
    RAW_MATERIAL_STATUS_CHANGED,
    RAW_MATERIAL_UPDATED,
)
from app.models.bom import BomComponent
from app.models.category import Category
from app.models.inventory import StockMovement
from app.models.raw_material import RawMaterial
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.schemas.raw_material import (
    RawMaterialCreateRequest,
    RawMaterialOut,
    RawMaterialStatusChangeRequest,
    RawMaterialUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service

router = APIRouter(prefix="/api/raw-materials", tags=["raw-materials"])

# See app/api/users.py's _SORT_FIELDS for the reasoning.
_SORT_FIELDS = {
    "code": RawMaterial.code,
    "name": RawMaterial.name,
    "created_at": RawMaterial.created_at,
}

_MAX_CODE_ATTEMPTS = 5


def _generate_raw_material_code(db: Session, organisation_id: int) -> str:
    existing = db.query(RawMaterial).filter(RawMaterial.organisation_id == organisation_id).count()
    return RAW_MATERIAL_CODE.format(existing + 1)


def get_raw_material_in_org(db: Session, raw_material_id: int, organisation_id: int) -> RawMaterial:
    """Exported (not prefixed `_`) -- app/api/raw_material_suppliers.py
    reuses this same lookup rather than duplicating it."""
    raw_material = (
        db.query(RawMaterial)
        .filter(RawMaterial.id == raw_material_id, RawMaterial.organisation_id == organisation_id)
        .first()
    )
    if raw_material is None:
        # 404 whether the id doesn't exist at all or belongs to another
        # organisation -- never confirm another organisation's material id
        # (docs/modules/organisation.md #3).
        raise NotFoundError("Raw material not found.")
    return raw_material


def _resolve_active_category(db: Session, category_id: int, organisation_id: int) -> Category:
    category = (
        db.query(Category)
        .filter(Category.id == category_id, Category.organisation_id == organisation_id, Category.is_active.is_(True))
        .first()
    )
    if category is None:
        raise ValidationError(
            "category_id must be an active category in your organisation.",
            fields={"category_id": "Not a valid active category in your organisation."},
        )
    return category


def _has_recorded_quantity(db: Session, raw_material_id: int) -> bool:
    """A BomComponent row's quantity, and RawMaterialInventory.quantity_on_hand,
    both implicitly mean "in this material's own unit" (StockMovement now
    records its own unit_of_measure_id explicitly, but that's just this
    row's own record of what was already true -- it's still always the
    material's own unit, never a different one). Once any such row
    exists, changing the material's unit would silently change what every
    already-recorded quantity means, with no conversion and no warning.
    RawMaterialInventory is not checked separately --
    app/services/inventory_service.py never creates one without a
    StockMovement in the same call."""
    has_component = (
        db.query(BomComponent.id).filter(BomComponent.raw_material_id == raw_material_id).first() is not None
    )
    if has_component:
        return True
    return db.query(StockMovement.id).filter(StockMovement.raw_material_id == raw_material_id).first() is not None


def _resolve_active_unit(
    db: Session, unit_of_measure_id: int, organisation_id: int, field: str = "unit_of_measure_id"
) -> UnitOfMeasure:
    unit = (
        db.query(UnitOfMeasure)
        .filter(
            UnitOfMeasure.id == unit_of_measure_id,
            UnitOfMeasure.organisation_id == organisation_id,
            UnitOfMeasure.is_active.is_(True),
        )
        .first()
    )
    if unit is None:
        raise ValidationError(
            f"{field} must be an active unit of measure in your organisation.",
            fields={field: "Not a valid active unit of measure in your organisation."},
        )
    return unit


@router.get("", response_model=PaginatedResponse[RawMaterialOut])
def list_raw_materials(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    include_inactive: bool = Query(False),
    q: str | None = Query(None, max_length=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[RawMaterialOut]:
    """Scoped to the caller's own organisation only. Open to any
    authenticated organisation member, same as every other master --
    Raw Material is reference data every future Procurement/BOM/
    Production/Inventory consumer needs to look up; only mutations are
    admin-gated."""
    query = db.query(RawMaterial).filter(RawMaterial.organisation_id == current_user.organisation_id)
    if not include_inactive:
        query = query.filter(RawMaterial.is_active.is_(True))
    query = apply_keyword_filter(query, q, RawMaterial.name, RawMaterial.code)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=RawMaterial.id)

    materials, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[RawMaterialOut.model_validate(m) for m in materials], pagination=pagination)


@router.get("/{raw_material_id}", response_model=RawMaterialOut)
def get_raw_material(
    raw_material_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> RawMaterial:
    return get_raw_material_in_org(db, raw_material_id, current_user.organisation_id)


@router.post("", response_model=RawMaterialOut, status_code=status.HTTP_201_CREATED)
def create_raw_material(
    payload: RawMaterialCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RawMaterial:
    """Admin-gated, same shape as POST /api/products. `code` is
    system-generated and retried against a collision, same pattern
    Supplier/Customer already use (per explicit user instruction,
    superseding this module's original caller-supplied code -- see
    docs/audit/RAW_MATERIALS_AUDIT.md #2 for the now-superseded
    jdk_clean precedent)."""
    _resolve_active_category(db, payload.category_id, admin.organisation_id)
    _resolve_active_unit(db, payload.unit_of_measure_id, admin.organisation_id)
    if payload.alternate_conversion_unit_of_measure_id is not None:
        _resolve_active_unit(
            db,
            payload.alternate_conversion_unit_of_measure_id,
            admin.organisation_id,
            field="alternate_conversion_unit_of_measure_id",
        )

    raw_material: RawMaterial | None = None
    last_error: IntegrityError | None = None
    for _ in range(_MAX_CODE_ATTEMPTS):
        code = _generate_raw_material_code(db, admin.organisation_id)
        raw_material = RawMaterial(
            organisation_id=admin.organisation_id,
            code=code,
            name=payload.name,
            category_id=payload.category_id,
            unit_of_measure_id=payload.unit_of_measure_id,
            description=payload.description,
            reference_cost=payload.reference_cost,
            alternate_conversion_unit_of_measure_id=payload.alternate_conversion_unit_of_measure_id,
            alternate_conversion_factor=payload.alternate_conversion_factor,
        )
        db.add(raw_material)
        try:
            db.flush()
            last_error = None
            break
        except IntegrityError as exc:
            db.rollback()
            last_error = exc
    if last_error is not None or raw_material is None:
        raise ConflictError(
            "A raw material with this name already exists, or a unique code could not be generated."
        ) from last_error

    audit_service.log_event(
        db,
        action=RAW_MATERIAL_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="raw_material",
        entity_id=raw_material.id,
        result="success",
        details=f"code: {raw_material.code}, name: {raw_material.name}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(raw_material)
    return raw_material


@router.patch("/{raw_material_id}", response_model=RawMaterialOut)
def update_raw_material(
    raw_material_id: int,
    payload: RawMaterialUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RawMaterial:
    """Admin-gated partial update. is_active has its own endpoint below.
    `code` cannot be changed here -- see RawMaterialUpdateRequest."""
    raw_material = get_raw_material_in_org(db, raw_material_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    if "category_id" in updates:
        _resolve_active_category(db, updates["category_id"], admin.organisation_id)
    if "unit_of_measure_id" in updates:
        _resolve_active_unit(db, updates["unit_of_measure_id"], admin.organisation_id)
        if updates["unit_of_measure_id"] != raw_material.unit_of_measure_id and _has_recorded_quantity(
            db, raw_material.id
        ):
            raise ValidationError(
                "unit_of_measure_id cannot be changed once this raw material has BOM components or "
                "stock movements recorded against it.",
                fields={
                    "unit_of_measure_id": "Cannot change once quantities have been recorded in the current unit."
                },
            )
    if updates.get("alternate_conversion_unit_of_measure_id") is not None:
        _resolve_active_unit(
            db,
            updates["alternate_conversion_unit_of_measure_id"],
            admin.organisation_id,
            field="alternate_conversion_unit_of_measure_id",
        )

    before = {field: getattr(raw_material, field) for field in updates}
    for field, value in updates.items():
        setattr(raw_material, field, value)

    if (
        "alternate_conversion_unit_of_measure_id" in updates
        or "alternate_conversion_factor" in updates
        or "unit_of_measure_id" in updates
    ):
        # Same both-or-neither discipline as UnitOfMeasure's
        # dimension/conversion_factor_to_base pair -- checked against the
        # merged post-update state since a partial update only sees the
        # fields actually sent (docs/modules/boms.md #5). Also re-checked
        # when only unit_of_measure_id changes (not just the alternate
        # fields themselves) -- otherwise changing a material's own unit
        # to match its already-configured alternate unit would silently
        # leave alternate_conversion_unit_of_measure_id ==
        # unit_of_measure_id (e.g. "1 BAG = 25 BAG"), an invariant this
        # same block already rejects on create.
        if (raw_material.alternate_conversion_unit_of_measure_id is None) != (
            raw_material.alternate_conversion_factor is None
        ):
            raise ValidationError(
                "alternate_conversion_unit_of_measure_id and alternate_conversion_factor "
                "must be provided together, or not at all.",
                fields={"alternate_conversion_factor": "Must be set together with the alternate unit, or both left unset."},
            )
        if raw_material.alternate_conversion_unit_of_measure_id == raw_material.unit_of_measure_id:
            raise ValidationError(
                "alternate_conversion_unit_of_measure_id must differ from unit_of_measure_id.",
                fields={"alternate_conversion_unit_of_measure_id": "Must differ from the material's own unit of measure."},
            )
        if raw_material.alternate_conversion_factor is not None and raw_material.alternate_conversion_factor <= 0:
            raise ValidationError(
                "alternate_conversion_factor must be greater than zero.",
                fields={"alternate_conversion_factor": "Must be greater than zero."},
            )

    db.add(raw_material)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A raw material with this name already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=RAW_MATERIAL_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="raw_material",
            entity_id=raw_material.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(raw_material)
    return raw_material


@router.patch("/{raw_material_id}/status", response_model=RawMaterialOut)
def change_raw_material_status(
    raw_material_id: int,
    payload: RawMaterialStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RawMaterial:
    """Admin-gated activate/deactivate. No delete guard is needed yet --
    nothing in jdk_erp references `raw_materials` (BOM/Purchase Order/
    Receipt/Production/Inventory are all unbuilt); jdk_clean itself has
    no such guard either despite having real consumers
    (docs/audit/RAW_MATERIALS_AUDIT.md #13), a gap explicitly not
    repeated once a first consumer exists here. Deactivating only governs
    whether the material can be *newly selected* -- the same rule already
    established for every other master. The Supplier<->Raw Material
    relationship (SupplierMaterial) is unaffected by deactivating the
    material -- it is a separate, explicit relationship, never silently
    modified as a side effect of this endpoint."""
    raw_material = get_raw_material_in_org(db, raw_material_id, admin.organisation_id)
    raw_material.is_active = payload.is_active
    db.add(raw_material)

    audit_service.log_event(
        db,
        action=RAW_MATERIAL_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="raw_material",
        entity_id=raw_material.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(raw_material)
    return raw_material
