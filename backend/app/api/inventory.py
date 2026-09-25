"""Controlled Stock Adjustments and Controlled Opening Stock -- the two
explicit, manual ways to write a verified stock fact outside the normal
receive/reverse flow: a correction (Adjustments) or a starting balance
(Opening Stock). Each is gated by its own inventory:* action
(app/services/inventory_scope.py), deliberately a different module_key
than `purchase:receive` -- warehouse receiving authority alone must
never also grant either. Also the ledger/balance reconciliation report
(GET /reconciliation) -- read-only, never a fix; the Stock Balance
audit's own noted gap, closed as a report rather than left unaddressed.
No dashboard, no approval workflow, no scheduling: these are the
mechanisms and the one report, nothing more."""

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import ValidationError
from app.models.audit_event import (
    INVENTORY_ADJUSTMENT_CREATED,
    INVENTORY_MODULE,
    INVENTORY_OPENING_STOCK_RECORDED,
)
from app.models.raw_material import RawMaterial
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.inventory import (
    AdjustmentOut,
    AdjustStockRequest,
    BalanceReconciliationOut,
    OpeningStockOut,
    ReconciliationReportOut,
    RecordOpeningStockRequest,
)
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


@router.post("/opening-stock", response_model=OpeningStockOut, status_code=status.HTTP_201_CREATED)
def create_opening_stock(
    payload: RecordOpeningStockRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OpeningStockOut:
    """Records Controlled Opening Stock: a new OPENING_STOCK ledger
    movement establishing a (raw material, warehouse) pair's starting
    balance, applied atomically, never a direct edit of quantity_on_hand
    or of any existing StockMovement. At most one per pair, ever -- a
    second submission for the same material/warehouse is rejected as a
    duplicate. The quantity is always in the raw material's own current
    stock unit, resolved here -- never accepted from the client."""
    inventory_scope.require_permission(db, current_user, inventory_scope.OPENING_STOCK)
    material = _resolve_active_raw_material(db, payload.raw_material_id, current_user.organisation_id)
    warehouse = _resolve_active_warehouse(db, payload.warehouse_id, current_user.organisation_id)

    movement = inventory_service.record_opening_stock(
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
        action=INVENTORY_OPENING_STOCK_RECORDED,
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
    return OpeningStockOut(
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


@router.get("/reconciliation", response_model=ReconciliationReportOut)
def get_reconciliation_report(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ReconciliationReportOut:
    """Every (raw material, warehouse) pair this organisation has a
    stock snapshot for, each compared against what its own ledger sums
    to -- read-only, never a fix. A mismatch is a data-integrity fact to
    investigate and correct with a Controlled Stock Adjustment, never
    something this report changes itself."""
    inventory_scope.require_permission(db, current_user, inventory_scope.RECONCILE)
    pairs = inventory_service.reconcile_balances(db, organisation_id=current_user.organisation_id)

    material_names = dict(
        db.query(RawMaterial.id, RawMaterial.name).filter(RawMaterial.id.in_({p.raw_material_id for p in pairs})).all()
    )
    warehouse_names = dict(
        db.query(Warehouse.id, Warehouse.name).filter(Warehouse.id.in_({p.warehouse_id for p in pairs})).all()
    )

    out_pairs = [
        BalanceReconciliationOut(
            raw_material_id=pair.raw_material_id,
            material_name=material_names.get(pair.raw_material_id, f"#{pair.raw_material_id}"),
            warehouse_id=pair.warehouse_id,
            warehouse_name=warehouse_names.get(pair.warehouse_id, f"#{pair.warehouse_id}"),
            ledger_sum=pair.ledger_sum,
            quantity_on_hand=pair.quantity_on_hand,
            difference=pair.difference,
            matches=pair.matches,
        )
        for pair in pairs
    ]
    return ReconciliationReportOut(
        pairs_checked=len(out_pairs),
        mismatches_found=sum(1 for p in out_pairs if not p.matches),
        pairs=out_pairs,
    )
