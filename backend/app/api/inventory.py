"""Controlled Stock Adjustments -- the one explicit, manual way to
correct a verified physical/system stock difference. Gated by
`inventory:adjust` (app/services/inventory_scope.py), deliberately a
different module_key than `purchase:receive` -- warehouse receiving
authority alone must never also grant adjustment authority. No listing,
no dashboard, no approval workflow: this pass is only the correction
mechanism itself, verified atomic and traceable in the ledger."""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import ValidationError
from app.models.audit_event import INVENTORY_ADJUSTMENT_CREATED, INVENTORY_MODULE
from app.models.raw_material import RawMaterial
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.inventory import AdjustmentOut, AdjustStockRequest
from app.services import audit_service, inventory_scope, inventory_service

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


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


def _resolve_active_warehouse(db: Session, warehouse_id: int, organisation_id: int) -> Warehouse:
    warehouse = (
        db.query(Warehouse)
        .filter(Warehouse.id == warehouse_id, Warehouse.organisation_id == organisation_id, Warehouse.is_active.is_(True))
        .first()
    )
    if warehouse is None:
        raise ValidationError(
            "warehouse_id must be an active warehouse in your organisation.",
            fields={"warehouse_id": "Not a valid active warehouse in your organisation."},
        )
    return warehouse


@router.post("/adjustments", response_model=AdjustmentOut, status_code=status.HTTP_201_CREATED)
def create_adjustment(
    payload: AdjustStockRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AdjustmentOut:
    """Records a Controlled Stock Adjustment: a new ADJUSTMENT ledger
    movement, applied to the balance atomically, never a direct edit of
    quantity_on_hand or of any existing StockMovement. The adjustment
    quantity is always in the raw material's own current stock unit,
    resolved here -- never accepted from the client."""
    inventory_scope.require_permission(db, current_user, inventory_scope.ADJUST)
    material = _resolve_active_raw_material(db, payload.raw_material_id, current_user.organisation_id)
    warehouse = _resolve_active_warehouse(db, payload.warehouse_id, current_user.organisation_id)

    movement = inventory_service.adjust_stock(
        db,
        organisation_id=current_user.organisation_id,
        raw_material_id=material.id,
        warehouse_id=warehouse.id,
        quantity=payload.quantity,
        unit_of_measure_id=material.unit_of_measure_id,
        reason=payload.reason,
        created_by_user_id=current_user.id,
    )
    quantity_on_hand = inventory_service.get_quantity_on_hand(db, raw_material_id=material.id, warehouse_id=warehouse.id)

    audit_service.log_event(
        db,
        action=INVENTORY_ADJUSTMENT_CREATED,
        module=INVENTORY_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="raw_material",
        entity_id=material.id,
        result="success",
        details=f"warehouse: {warehouse.name}, quantity: {payload.quantity}, reason: {payload.reason}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    unit = db.query(UnitOfMeasure).filter(UnitOfMeasure.id == material.unit_of_measure_id).first()
    return AdjustmentOut(
        id=movement.id,
        raw_material_id=material.id,
        material_name=material.name,
        warehouse_id=warehouse.id,
        warehouse_name=warehouse.name,
        quantity=movement.quantity,
        unit_of_measure_id=material.unit_of_measure_id,
        unit_code=unit.code if unit is not None else "",
        reason=payload.reason,
        created_by_user_id=current_user.id,
        created_by_name=current_user.full_name,
        created_at=movement.created_at,
        quantity_on_hand=quantity_on_hand,
    )
