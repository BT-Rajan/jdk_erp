from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.api.raw_materials import get_raw_material_in_org
from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.audit_event import (
    MASTER_DATA_MODULE,
    SUPPLIER_MATERIAL_ADDED,
    SUPPLIER_MATERIAL_REMOVED,
    SUPPLIER_MATERIAL_UPDATED,
)
from app.models.supplier import Supplier
from app.models.supplier_material import SupplierMaterial
from app.models.user import User
from app.schemas.raw_material import (
    SupplierMaterialCreateRequest,
    SupplierMaterialOut,
    SupplierMaterialUpdateRequest,
)
from app.services import audit_service

router = APIRouter(prefix="/api/raw-materials/{raw_material_id}/suppliers", tags=["raw-materials"])


def _resolve_active_supplier(db: Session, supplier_id: int, organisation_id: int) -> Supplier:
    supplier = (
        db.query(Supplier)
        .filter(Supplier.id == supplier_id, Supplier.organisation_id == organisation_id, Supplier.is_active.is_(True))
        .first()
    )
    if supplier is None:
        raise ValidationError(
            "supplier_id must be an active supplier in your organisation.",
            fields={"supplier_id": "Not a valid active supplier in your organisation."},
        )
    return supplier


def _get_link(db: Session, raw_material_id: int, link_id: int) -> SupplierMaterial:
    link = (
        db.query(SupplierMaterial)
        .filter(SupplierMaterial.id == link_id, SupplierMaterial.raw_material_id == raw_material_id)
        .first()
    )
    if link is None:
        raise NotFoundError("Supplier relationship not found.")
    return link


def _enforce_single_preferred(db: Session, raw_material_id: int, keep_id: int) -> None:
    """At most one preferred supplier per raw material -- service-side
    only, matching jdk_clean's own real, deliberate choice
    (docs/audit/RAW_MATERIALS_AUDIT.md #5): silently un-set every other
    row rather than reject the write."""
    others = (
        db.query(SupplierMaterial)
        .filter(
            SupplierMaterial.raw_material_id == raw_material_id,
            SupplierMaterial.id != keep_id,
            SupplierMaterial.is_preferred.is_(True),
        )
        .all()
    )
    for other in others:
        other.is_preferred = False
        db.add(other)


@router.get("", response_model=list[SupplierMaterialOut])
def list_raw_material_suppliers(
    raw_material_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[SupplierMaterial]:
    """Open to any authenticated organisation member, same as the raw
    material record itself -- which suppliers can provide a material is
    reference data Procurement needs to look up, not a privileged view."""
    get_raw_material_in_org(db, raw_material_id, current_user.organisation_id)
    return (
        db.query(SupplierMaterial)
        .filter(SupplierMaterial.raw_material_id == raw_material_id)
        .order_by(SupplierMaterial.id)
        .all()
    )


@router.post("", response_model=SupplierMaterialOut, status_code=status.HTTP_201_CREATED)
def add_raw_material_supplier(
    raw_material_id: int,
    payload: SupplierMaterialCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SupplierMaterial:
    """Admin-gated -- managing which suppliers can provide a material is
    a master-data administration action, same gate as every mutation on
    Raw Material/Supplier themselves."""
    raw_material = get_raw_material_in_org(db, raw_material_id, admin.organisation_id)
    _resolve_active_supplier(db, payload.supplier_id, admin.organisation_id)

    link = SupplierMaterial(
        supplier_id=payload.supplier_id,
        raw_material_id=raw_material.id,
        supplier_material_code=payload.supplier_material_code,
        purchase_price=payload.purchase_price,
        lead_time_days=payload.lead_time_days,
        moq=payload.moq,
        max_supply_quantity=payload.max_supply_quantity,
        is_preferred=payload.is_preferred,
    )
    db.add(link)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("This supplier is already linked to this raw material.") from exc

    if link.is_preferred:
        _enforce_single_preferred(db, raw_material.id, link.id)

    audit_service.log_event(
        db,
        action=SUPPLIER_MATERIAL_ADDED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="raw_material",
        entity_id=raw_material.id,
        result="success",
        details=f"supplier_id: {link.supplier_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(link)
    return link


@router.patch("/{link_id}", response_model=SupplierMaterialOut)
def update_raw_material_supplier(
    raw_material_id: int,
    link_id: int,
    payload: SupplierMaterialUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SupplierMaterial:
    """Admin-gated partial update of the relationship's terms.
    `supplier_id`/`raw_material_id` are immutable -- see
    SupplierMaterialUpdateRequest."""
    get_raw_material_in_org(db, raw_material_id, admin.organisation_id)
    link = _get_link(db, raw_material_id, link_id)

    updates = payload.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(link, field, value)
    db.add(link)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("This supplier is already linked to this raw material.") from exc

    if updates.get("is_preferred") is True:
        _enforce_single_preferred(db, raw_material_id, link.id)

    audit_service.log_event(
        db,
        action=SUPPLIER_MATERIAL_UPDATED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="raw_material",
        entity_id=raw_material_id,
        result="success",
        details=f"supplier_material_id: {link.id}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(link)
    return link


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_raw_material_supplier(
    raw_material_id: int,
    link_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Admin-gated. A real delete, not a status toggle -- severing that
    this supplier can provide this material at all is different from
    pausing it (SupplierMaterialUpdateRequest.is_active covers pausing).
    No historical transaction references this row yet (Purchase Order
    doesn't exist in this codebase), so nothing is orphaned by removing
    it outright (docs/modules/raw_materials.md #7)."""
    get_raw_material_in_org(db, raw_material_id, admin.organisation_id)
    link = _get_link(db, raw_material_id, link_id)

    audit_service.log_event(
        db,
        action=SUPPLIER_MATERIAL_REMOVED,
        module=MASTER_DATA_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="raw_material",
        entity_id=raw_material_id,
        result="success",
        details=f"supplier_id: {link.supplier_id}",
        ip_address=request.client.host if request.client else None,
    )
    db.delete(link)
    db.commit()
