"""Finished Goods Inventory -- the current stock position of
manufactured Products, backed by its own append-only ledger
(app/models/finished_goods_inventory.py), deliberately separate from
Raw Material Inventory (app/api/inventory.py, untouched by this
module). Gated by inventory_scope.py's own actions -- `view` for the
two read endpoints below, `adjust` reused unchanged from Raw Material
Inventory for the one write endpoint, per this module's own explicit
"reuse existing RBAC" instruction.

Only one write action exists here: a Controlled Finished Goods Stock
Adjustment. There is no receive/production-completion or
issue/delivery endpoint -- this codebase has no Production Completion
or Delivery/Dispatch workflow yet to drive them (see
app/services/finished_goods_inventory_service.py's own module
docstring for the inspection this is based on); the service functions
those future events call into already exist, ready to be wired in."""

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.errors import ValidationError
from app.models.audit_event import FINISHED_GOODS_ADJUSTMENT_CREATED, INVENTORY_MODULE
from app.models.category import Category
from app.models.product import Product
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.warehouse import Warehouse
from app.schemas.finished_goods_inventory import (
    IN_STOCK,
    NO_RECORD,
    OUT_OF_STOCK,
    AdjustFinishedGoodsStockRequest,
    FinishedGoodsAdjustmentOut,
    FinishedGoodsMovementOut,
    FinishedGoodsStockPositionOut,
)
from app.services import audit_service, finished_goods_inventory_service, inventory_scope

router = APIRouter(prefix="/api/finished-goods-inventory", tags=["finished-goods-inventory"])


def _resolve_active_product(db: Session, product_id: int, organisation_id: int) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.organisation_id == organisation_id, Product.is_active.is_(True))
        .first()
    )
    if product is None:
        raise ValidationError(
            "product_id must be an active product in your organisation.",
            fields={"product_id": "Not a valid active product in your organisation."},
        )
    return product


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


@router.get("", response_model=list[FinishedGoodsStockPositionOut])
def list_stock_positions(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[FinishedGoodsStockPositionOut]:
    """The Stock Position screen's own data source. Every Product in
    the organisation is represented -- not just the ones with a
    Finished Goods snapshot -- so a Product that has never been
    produced, delivered or adjusted still shows (status `no_record`,
    with no warehouse/quantity to report), distinguishable from a real
    ledger that nets to zero (`out_of_stock`). Balances themselves are
    never computed here: each snapshot row's quantity_on_hand is read
    as-is from finished_goods_inventory_service.list_stock_positions,
    the same authoritative source the movement-history endpoint below
    reconciles against."""
    inventory_scope.require_permission(db, current_user, inventory_scope.VIEW)

    positions = finished_goods_inventory_service.list_stock_positions(db, organisation_id=current_user.organisation_id)
    all_products = db.query(Product).filter(Product.organisation_id == current_user.organisation_id).all()
    products = {p.id: p for p in all_products}

    warehouse_ids = {p.warehouse_id for p in positions}
    warehouses = {w.id: w for w in db.query(Warehouse).filter(Warehouse.id.in_(warehouse_ids))} if warehouse_ids else {}
    category_ids = {p.category_id for p in all_products}
    categories = {c.id: c for c in db.query(Category).filter(Category.id.in_(category_ids))} if category_ids else {}
    unit_ids = {p.unit_of_measure_id for p in all_products}
    units = {u.id: u for u in db.query(UnitOfMeasure).filter(UnitOfMeasure.id.in_(unit_ids))} if unit_ids else {}

    def _row(
        product: Product,
        *,
        warehouse: Warehouse | None,
        quantity_on_hand,
        status: str,
    ) -> FinishedGoodsStockPositionOut:
        unit = units.get(product.unit_of_measure_id)
        category = categories.get(product.category_id)
        return FinishedGoodsStockPositionOut(
            product_id=product.id,
            product_code=product.code,
            product_name=product.name,
            product_is_active=product.is_active,
            category_id=product.category_id,
            category_name=category.name if category is not None else "",
            warehouse_id=warehouse.id if warehouse is not None else None,
            warehouse_name=warehouse.name if warehouse is not None else None,
            unit_of_measure_id=product.unit_of_measure_id,
            unit_code=unit.code if unit is not None else "",
            quantity_on_hand=quantity_on_hand,
            status=status,
        )

    out: list[FinishedGoodsStockPositionOut] = []
    products_with_record: set[int] = set()
    for position in positions:
        product = products.get(position.product_id)
        warehouse = warehouses.get(position.warehouse_id)
        if product is None or warehouse is None:
            continue
        products_with_record.add(product.id)
        out.append(
            _row(
                product,
                warehouse=warehouse,
                quantity_on_hand=position.quantity_on_hand,
                status=IN_STOCK if position.quantity_on_hand > 0 else OUT_OF_STOCK,
            )
        )

    for product in all_products:
        if product.id in products_with_record:
            continue
        out.append(_row(product, warehouse=None, quantity_on_hand=None, status=NO_RECORD))

    out.sort(key=lambda row: (row.product_name, row.warehouse_name or ""))
    return out


@router.get("/movements", response_model=list[FinishedGoodsMovementOut])
def get_movement_history(
    product_id: int = Query(...),
    warehouse_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[FinishedGoodsMovementOut]:
    """A Finished Good's movement history, from its Stock Position row
    (rule 6) -- newest first, each with the resulting balance it left
    the pair at."""
    inventory_scope.require_permission(db, current_user, inventory_scope.VIEW)
    product = _resolve_active_product(db, product_id, current_user.organisation_id)
    _resolve_active_warehouse(db, warehouse_id, current_user.organisation_id)

    entries = finished_goods_inventory_service.get_movement_history(db, product_id=product.id, warehouse_id=warehouse_id)
    if not entries:
        return []

    user_ids = {e.movement.created_by_user_id for e in entries if e.movement.created_by_user_id is not None}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids))} if user_ids else {}
    unit = db.query(UnitOfMeasure).filter(UnitOfMeasure.id == product.unit_of_measure_id).first()

    return [
        FinishedGoodsMovementOut(
            id=entry.movement.id,
            movement_type=entry.movement.movement_type,
            quantity=entry.movement.quantity,
            unit_of_measure_id=entry.movement.unit_of_measure_id,
            unit_code=unit.code if unit is not None else "",
            resulting_balance=entry.resulting_balance,
            reference_type=entry.movement.reference_type,
            reference_id=entry.movement.reference_id,
            created_by_user_id=entry.movement.created_by_user_id,
            created_by_name=(
                users[entry.movement.created_by_user_id].full_name
                if entry.movement.created_by_user_id in users
                else None
            ),
            created_at=entry.movement.created_at,
        )
        for entry in entries
    ]


@router.post("/adjustments", response_model=FinishedGoodsAdjustmentOut, status_code=status.HTTP_201_CREATED)
def create_finished_goods_adjustment(
    payload: AdjustFinishedGoodsStockRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinishedGoodsAdjustmentOut:
    """Records a Controlled Finished Goods Stock Adjustment: a new
    ADJUSTMENT ledger movement, applied to the balance atomically, never
    a direct edit of quantity_on_hand or of any existing
    FinishedGoodsMovement. Reuses inventory_scope.ADJUST unchanged --
    the same permission a Raw Material Stock Adjustment already
    requires, per this module's own "reuse existing RBAC" instruction,
    not a new grant a user could hold for Finished Goods without also
    holding it for Raw Materials (or vice versa)."""
    inventory_scope.require_permission(db, current_user, inventory_scope.ADJUST)
    product = _resolve_active_product(db, payload.product_id, current_user.organisation_id)
    warehouse = _resolve_active_warehouse(db, payload.warehouse_id, current_user.organisation_id)

    movement = finished_goods_inventory_service.adjust_finished_goods_stock(
        db,
        organisation_id=current_user.organisation_id,
        product_id=product.id,
        warehouse_id=warehouse.id,
        quantity=payload.quantity,
        unit_of_measure_id=product.unit_of_measure_id,
        reason=payload.reason,
        created_by_user_id=current_user.id,
    )
    quantity_on_hand = finished_goods_inventory_service.get_quantity_on_hand(
        db, product_id=product.id, warehouse_id=warehouse.id
    )

    audit_service.log_event(
        db,
        action=FINISHED_GOODS_ADJUSTMENT_CREATED,
        module=INVENTORY_MODULE,
        organisation_id=current_user.organisation_id,
        actor_user_id=current_user.id,
        entity_type="product",
        entity_id=product.id,
        result="success",
        details=f"warehouse: {warehouse.name}, quantity: {payload.quantity}, reason: {payload.reason}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()

    unit = db.query(UnitOfMeasure).filter(UnitOfMeasure.id == product.unit_of_measure_id).first()
    return FinishedGoodsAdjustmentOut(
        id=movement.id,
        product_id=product.id,
        product_name=product.name,
        warehouse_id=warehouse.id,
        warehouse_name=warehouse.name,
        quantity=movement.quantity,
        unit_of_measure_id=product.unit_of_measure_id,
        unit_code=unit.code if unit is not None else "",
        reason=payload.reason,
        created_by_user_id=current_user.id,
        created_by_name=current_user.full_name,
        created_at=movement.created_at,
        quantity_on_hand=quantity_on_hand,
    )
