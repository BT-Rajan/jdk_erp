from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, ValidationError
from app.core.list_query import apply_sort, paginate
from app.models.audit_event import (
    BOM_COMPONENT_ADDED,
    BOM_COMPONENT_REMOVED,
    BOM_COMPONENT_UPDATED,
    BOM_CREATED,
    BOM_STATUS_CHANGED,
    BOM_UPDATED,
    MASTER_DATA_MODULE,
)
from app.models.bom import ACTIVE, DRAFT, Bom, BomComponent
from app.models.product import Product
from app.models.raw_material import RawMaterial
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.schemas.bom import (
    BomComponentCreateRequest,
    BomComponentOut,
    BomComponentUpdateRequest,
    BomCreateRequest,
    BomOut,
    BomStatusChangeRequest,
    BomUpdateRequest,
    CalculateRequirementsRequest,
    CalculateRequirementsResponse,
    RequirementLine,
)
from app.schemas.pagination import PaginatedResponse
from app.services import audit_service, bom_service

router = APIRouter(prefix="/api/boms", tags=["boms"])

_SORT_FIELDS = {
    "product_id": Bom.product_id,
    "status": Bom.status,
    "created_at": Bom.created_at,
}


class _UnitCache:
    """A component's own material and unit are looked up at most once
    per BOM read, even when several components share the same unit --
    the BOM master is tiny (a handful of components each), so this is
    proportionate caching, not a general-purpose data-loading layer
    (docs/modules/boms.md #16)."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._units: dict[int, UnitOfMeasure] = {}

    def get(self, unit_id: int) -> UnitOfMeasure:
        if unit_id not in self._units:
            unit = self._db.query(UnitOfMeasure).filter(UnitOfMeasure.id == unit_id).first()
            if unit is None:
                raise NotFoundError("Unit of measure not found.")
            self._units[unit_id] = unit
        return self._units[unit_id]


def _get_bom_in_org(db: Session, bom_id: int, organisation_id: int) -> Bom:
    bom = db.query(Bom).filter(Bom.id == bom_id, Bom.organisation_id == organisation_id).first()
    if bom is None:
        raise NotFoundError("BOM not found.")
    return bom


def _get_product_in_org_or_404(db: Session, product_id: int, organisation_id: int) -> Product:
    product = db.query(Product).filter(Product.id == product_id, Product.organisation_id == organisation_id).first()
    if product is None:
        raise NotFoundError("Product not found.")
    return product


def _resolve_active_raw_material(db: Session, raw_material_id: int, organisation_id: int) -> RawMaterial:
    material = (
        db.query(RawMaterial)
        .filter(
            RawMaterial.id == raw_material_id,
            RawMaterial.organisation_id == organisation_id,
            RawMaterial.is_active.is_(True),
        )
        .first()
    )
    if material is None:
        raise ValidationError(
            "raw_material_id must be an active raw material in your organisation.",
            fields={"raw_material_id": "Not a valid active raw material in your organisation."},
        )
    return material


def _get_component(db: Session, bom_id: int, component_id: int) -> BomComponent:
    component = (
        db.query(BomComponent).filter(BomComponent.id == component_id, BomComponent.bom_id == bom_id).first()
    )
    if component is None:
        raise NotFoundError("BOM component not found.")
    return component


def _build_component_out(
    db: Session,
    component: BomComponent,
    product: Product,
    product_unit: UnitOfMeasure,
    base_quantity: Decimal,
    units: _UnitCache,
) -> BomComponentOut:
    material = db.query(RawMaterial).filter(RawMaterial.id == component.raw_material_id).first()
    material_unit = units.get(material.unit_of_measure_id)
    alt_unit = (
        units.get(material.alternate_conversion_unit_of_measure_id)
        if material.alternate_conversion_unit_of_measure_id is not None
        else None
    )
    conversion = bom_service.check_component_conversion(product, product_unit, material, material_unit, alt_unit)
    percentage = None
    if conversion.ratio_to_product_unit is not None:
        percentage = bom_service.component_percentage(component.quantity, conversion.ratio_to_product_unit, base_quantity)
    return BomComponentOut(
        id=component.id,
        raw_material_id=component.raw_material_id,
        quantity=component.quantity,
        percentage=percentage,
        conversion_ok=conversion.ratio_to_product_unit is not None,
        conversion_error=conversion.error,
    )


def _build_bom_out(db: Session, bom: Bom) -> BomOut:
    product = db.query(Product).filter(Product.id == bom.product_id).first()
    units = _UnitCache(db)
    product_unit = units.get(product.unit_of_measure_id)
    components = db.query(BomComponent).filter(BomComponent.bom_id == bom.id).order_by(BomComponent.id).all()
    component_outs = [
        _build_component_out(db, component, product, product_unit, bom.base_quantity, units) for component in components
    ]
    return BomOut(
        id=bom.id,
        organisation_id=bom.organisation_id,
        product_id=bom.product_id,
        base_quantity=bom.base_quantity,
        status=bom.status,
        notes=bom.notes,
        components=component_outs,
    )


@router.get("", response_model=PaginatedResponse[BomOut])
def list_boms(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort_by: str | None = Query(None),
    sort_direction: Literal["asc", "desc"] = Query("asc"),
    product_id: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedResponse[BomOut]:
    """Scoped to the caller's own organisation only. Open to any
    authenticated organisation member -- a future Feasibility/Production
    consumer (and anyone checking a recipe) needs to look this up; only
    mutations are admin-gated. `product_id` looks up the one BOM for a
    given product directly (docs/modules/boms.md #10: exactly one BOM
    per product)."""
    query = db.query(Bom).filter(Bom.organisation_id == current_user.organisation_id)
    if product_id is not None:
        query = query.filter(Bom.product_id == product_id)
    query = apply_sort(query, sort_by, sort_direction, _SORT_FIELDS, default=Bom.id)

    boms, pagination = paginate(query, page, page_size)
    return PaginatedResponse(data=[_build_bom_out(db, bom) for bom in boms], pagination=pagination)


@router.get("/{bom_id}", response_model=BomOut)
def get_bom(bom_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> BomOut:
    bom = _get_bom_in_org(db, bom_id, current_user.organisation_id)
    return _build_bom_out(db, bom)


@router.post("", response_model=BomOut, status_code=status.HTTP_201_CREATED)
def create_bom(
    payload: BomCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BomOut:
    """Admin-gated. Always starts `draft` and empty -- components are
    added afterward (docs/modules/boms.md #10). `product_id` must be an
    active product in the caller's own organisation; the BOM's base unit
    is always that product's own `unit_of_measure_id`, never a
    separately stored/selectable value (docs/modules/boms.md #4)."""
    product = _get_product_in_org_or_404(db, payload.product_id, admin.organisation_id)
    if not product.is_active:
        raise ValidationError(
            "product_id must be an active product in your organisation.",
            fields={"product_id": "Not a valid active product in your organisation."},
        )

    bom = Bom(
        organisation_id=admin.organisation_id,
        product_id=payload.product_id,
        base_quantity=payload.base_quantity,
        status=DRAFT,
        notes=payload.notes,
    )
    db.add(bom)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A BOM for this product already exists.") from exc

    audit_service.log_event(
        db,
        action=BOM_CREATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="bom",
        entity_id=bom.id,
        result="success",
        details=f"product_id: {bom.product_id}, base_quantity: {bom.base_quantity}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(bom)
    return _build_bom_out(db, bom)


@router.patch("/{bom_id}", response_model=BomOut)
def update_bom(
    bom_id: int,
    payload: BomUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BomOut:
    """Admin-gated partial update of the header. Changing `base_quantity`
    never invalidates a component's own unit conversion (conversion
    depends only on which units are involved, not on quantities), so no
    re-validation is needed here -- only the activation gate
    (PATCH .../status) re-checks conversions."""
    bom = _get_bom_in_org(db, bom_id, admin.organisation_id)

    updates = payload.model_dump(exclude_unset=True)
    before = {field: getattr(bom, field) for field in updates}
    for field, value in updates.items():
        setattr(bom, field, value)
    db.add(bom)
    db.flush()

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=BOM_UPDATED,
            module=MASTER_DATA_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="bom",
            entity_id=bom.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(bom)
    return _build_bom_out(db, bom)


@router.patch("/{bom_id}/status", response_model=BomOut)
def change_bom_status(
    bom_id: int,
    payload: BomStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BomOut:
    """Admin-gated. Moving to `active` requires passing full validation
    (docs/modules/boms.md #9/#10): at least one component, and every
    existing component's unit conversion still resolvable -- a defensive
    re-check, since a component is already validated when added (see
    add_bom_component below), but a unit's dimension or a material's
    conversion configuration could have changed since. Moving back to
    `draft` has no such gate -- a BOM can always be pulled back for
    editing."""
    bom = _get_bom_in_org(db, bom_id, admin.organisation_id)

    if payload.status == ACTIVE and bom.status != ACTIVE:
        product = db.query(Product).filter(Product.id == bom.product_id).first()
        units = _UnitCache(db)
        product_unit = units.get(product.unit_of_measure_id)
        components = db.query(BomComponent).filter(BomComponent.bom_id == bom.id).all()
        if not components:
            raise BusinessRuleError("Cannot activate a BOM with no components.")
        for component in components:
            material = db.query(RawMaterial).filter(RawMaterial.id == component.raw_material_id).first()
            material_unit = units.get(material.unit_of_measure_id)
            alt_unit = (
                units.get(material.alternate_conversion_unit_of_measure_id)
                if material.alternate_conversion_unit_of_measure_id is not None
                else None
            )
            bom_service.require_valid_component_conversion(product, product_unit, material, material_unit, alt_unit)

    bom.status = payload.status
    db.add(bom)

    audit_service.log_event(
        db,
        action=BOM_STATUS_CHANGED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="bom",
        entity_id=bom.id,
        result="success",
        details=f"status: {payload.status}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(bom)
    return _build_bom_out(db, bom)


@router.post("/{bom_id}/components", response_model=BomOut, status_code=status.HTTP_201_CREATED)
def add_bom_component(
    bom_id: int,
    payload: BomComponentCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BomOut:
    """Admin-gated. Rejects (422) if no valid quantity conversion exists
    between the BOM's Product and this Raw Material's own unit
    (docs/modules/boms.md #5) -- checked here, at save time, not only at
    activation, per the spec's own "before a BoM can be saved" wording."""
    bom = _get_bom_in_org(db, bom_id, admin.organisation_id)
    material = _resolve_active_raw_material(db, payload.raw_material_id, admin.organisation_id)

    product = db.query(Product).filter(Product.id == bom.product_id).first()
    units = _UnitCache(db)
    product_unit = units.get(product.unit_of_measure_id)
    material_unit = units.get(material.unit_of_measure_id)
    alt_unit = (
        units.get(material.alternate_conversion_unit_of_measure_id)
        if material.alternate_conversion_unit_of_measure_id is not None
        else None
    )
    bom_service.require_valid_component_conversion(product, product_unit, material, material_unit, alt_unit)

    component = BomComponent(bom_id=bom.id, raw_material_id=payload.raw_material_id, quantity=payload.quantity)
    db.add(component)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("This raw material is already a component of this BOM.") from exc

    audit_service.log_event(
        db,
        action=BOM_COMPONENT_ADDED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="bom",
        entity_id=bom.id,
        result="success",
        details=f"raw_material_id: {component.raw_material_id}, quantity: {component.quantity}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(bom)
    return _build_bom_out(db, bom)


@router.patch("/{bom_id}/components/{component_id}", response_model=BomOut)
def update_bom_component(
    bom_id: int,
    component_id: int,
    payload: BomComponentUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> BomOut:
    """Admin-gated. Only `quantity` is editable -- changing it never
    affects unit-conversion validity (that depends only on which units
    are involved), so no re-validation beyond the schema's positive-
    quantity check is needed."""
    bom = _get_bom_in_org(db, bom_id, admin.organisation_id)
    component = _get_component(db, bom.id, component_id)

    before_quantity = component.quantity
    component.quantity = payload.quantity
    db.add(component)
    db.flush()

    audit_service.log_event(
        db,
        action=BOM_COMPONENT_UPDATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="bom",
        entity_id=bom.id,
        result="success",
        details=f"raw_material_id: {component.raw_material_id}, quantity: {before_quantity} -> {component.quantity}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(bom)
    return _build_bom_out(db, bom)


@router.delete("/{bom_id}/components/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_bom_component(
    bom_id: int,
    component_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Admin-gated. A real delete -- no historical transaction references
    a BOM component yet (Production Order doesn't exist in this
    codebase), so nothing is orphaned by removing it outright, the same
    reasoning already applied to SupplierMaterial."""
    bom = _get_bom_in_org(db, bom_id, admin.organisation_id)
    component = _get_component(db, bom.id, component_id)

    audit_service.log_event(
        db,
        action=BOM_COMPONENT_REMOVED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="bom",
        entity_id=bom.id,
        result="success",
        details=f"raw_material_id: {component.raw_material_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.delete(component)
    db.commit()


@router.post("/{bom_id}/calculate-requirements", response_model=CalculateRequirementsResponse)
def calculate_requirements(
    bom_id: int,
    payload: CalculateRequirementsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CalculateRequirementsResponse:
    """Open to any authenticated organisation member -- a stateless
    calculation, not a transaction (docs/modules/boms.md #7/#11): given a
    hypothetical production quantity (assumed expressed in the BOM's own
    base unit, the Product's unit_of_measure), returns each component's
    required quantity in that component's own unit. Only a valid
    `active` BOM may be used (docs/modules/boms.md #10) -- this never
    persists a "production order" of its own; a future Production Order
    module is responsible for snapshotting whatever result it reads here
    onto its own transaction row."""
    bom = _get_bom_in_org(db, bom_id, current_user.organisation_id)
    if bom.status != ACTIVE:
        raise BusinessRuleError("Only an active BOM can be used to calculate production requirements.")

    components = db.query(BomComponent).filter(BomComponent.bom_id == bom.id).order_by(BomComponent.id).all()
    requirements = [
        RequirementLine(
            raw_material_id=component.raw_material_id,
            required_quantity=bom_service.required_quantity(component.quantity, payload.production_quantity, bom.base_quantity),
            unit_of_measure_id=db.query(RawMaterial.unit_of_measure_id)
            .filter(RawMaterial.id == component.raw_material_id)
            .scalar(),
        )
        for component in components
    ]
    return CalculateRequirementsResponse(
        product_id=bom.product_id, production_quantity=payload.production_quantity, requirements=requirements
    )
