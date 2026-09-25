"""Direct service-level tests for Finished Goods Inventory (not through
the HTTP API, which has its own coverage in
test_finished_goods_inventory_api.py) -- the same "prove the guards
hold at the one place they're supposed to" discipline
test_inventory_service.py already applies to Raw Material Inventory.
Covers the Tests section of the Finished Goods Inventory spec: IN
increases stock, OUT decreases stock, negative stock is rejected,
duplicate source transactions cannot double-apply, ledger/balance stay
atomic, a movement is never edited/deleted, and Finished Goods stock is
provably separate from Raw Material stock."""
from decimal import Decimal

import pytest
from sqlalchemy import func

from app.core.database import SessionLocal
from app.core.errors import BusinessRuleError, ConflictError
from app.models.finished_goods_inventory import (
    ADJUSTMENT,
    ADJUSTMENT_REFERENCE,
    DELIVERY,
    PRODUCTION_COMPLETION,
    FinishedGoodsAdjustment,
    FinishedGoodsInventory,
    FinishedGoodsMovement,
)
from app.models.inventory import RawMaterialInventory, StockMovement
from app.services import finished_goods_inventory_service, inventory_service

REFERENCE_TYPE = "test_reference"


def _receive(db_session, organisation, widget_product, warehouse_1, quantity, reference_id=1):
    return finished_goods_inventory_service.receive_finished_goods(
        db_session,
        organisation_id=organisation.id,
        product_id=widget_product.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal(quantity),
        unit_of_measure_id=widget_product.unit_of_measure_id,
        reference_type=REFERENCE_TYPE,
        reference_id=reference_id,
        created_by_user_id=None,
    )


def _issue(db_session, organisation, widget_product, warehouse_1, quantity, reference_id=1):
    return finished_goods_inventory_service.issue_finished_goods(
        db_session,
        organisation_id=organisation.id,
        product_id=widget_product.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal(quantity),
        unit_of_measure_id=widget_product.unit_of_measure_id,
        reference_type=REFERENCE_TYPE,
        reference_id=reference_id,
        created_by_user_id=None,
    )


def _adjust(db_session, organisation, widget_product, warehouse_1, quantity, reason="Cycle count correction"):
    return finished_goods_inventory_service.adjust_finished_goods_stock(
        db_session,
        organisation_id=organisation.id,
        product_id=widget_product.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal(quantity),
        unit_of_measure_id=widget_product.unit_of_measure_id,
        reason=reason,
        created_by_user_id=None,
    )


def _on_hand(db_session, widget_product, warehouse_1) -> Decimal:
    row = (
        db_session.query(FinishedGoodsInventory)
        .filter(
            FinishedGoodsInventory.product_id == widget_product.id,
            FinishedGoodsInventory.warehouse_id == warehouse_1.id,
        )
        .first()
    )
    return row.quantity_on_hand if row is not None else Decimal("0")


def _ledger_sum(db_session, widget_product, warehouse_1) -> Decimal:
    total = (
        db_session.query(func.sum(FinishedGoodsMovement.quantity))
        .filter(
            FinishedGoodsMovement.product_id == widget_product.id,
            FinishedGoodsMovement.warehouse_id == warehouse_1.id,
        )
        .scalar()
    )
    return total if total is not None else Decimal("0")


# --- 1. Finished Goods stock is separate from Raw Material stock --------------------------------


def test_finished_goods_stock_is_separate_from_raw_material_stock(
    db_session, organisation, widget_product, cement_raw_material, warehouse_1
):
    """A Product and a Raw Material can even share the same id space --
    the two ledgers/balances never collide because they live in wholly
    separate tables, keyed by product_id vs raw_material_id."""
    _receive(db_session, organisation, widget_product, warehouse_1, "40")
    inventory_service.receive_stock(
        db_session,
        organisation_id=organisation.id,
        raw_material_id=cement_raw_material.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal("999"),
        unit_of_measure_id=cement_raw_material.unit_of_measure_id,
        reference_type=REFERENCE_TYPE,
        reference_id=1,
        created_by_user_id=None,
    )
    db_session.commit()

    assert _on_hand(db_session, widget_product, warehouse_1) == Decimal("40")
    assert db_session.query(RawMaterialInventory).count() == 1
    assert db_session.query(FinishedGoodsInventory).count() == 1
    assert db_session.query(StockMovement).count() == 1
    assert db_session.query(FinishedGoodsMovement).count() == 1
    # No RawMaterialInventory row was touched by the Finished Goods
    # receive, and vice versa -- the Raw Material balance is exactly the
    # 999 its own movement posted, not affected by the 40 Finished Goods
    # units at all.
    rm_row = db_session.query(RawMaterialInventory).first()
    assert rm_row.quantity_on_hand == Decimal("999")


# --- 2. An IN movement increases stock -----------------------------------------------------------


def test_production_completion_increases_finished_goods_stock(db_session, organisation, widget_product, warehouse_1):
    movement = _receive(db_session, organisation, widget_product, warehouse_1, "100")
    db_session.commit()

    assert movement.movement_type == PRODUCTION_COMPLETION
    assert movement.quantity == Decimal("100")
    assert _on_hand(db_session, widget_product, warehouse_1) == Decimal("100")


def test_a_second_production_completion_further_increases_stock(db_session, organisation, widget_product, warehouse_1):
    _receive(db_session, organisation, widget_product, warehouse_1, "100", reference_id=1)
    _receive(db_session, organisation, widget_product, warehouse_1, "50", reference_id=2)
    db_session.commit()

    assert _on_hand(db_session, widget_product, warehouse_1) == Decimal("150")


# --- 3. An OUT movement decreases stock ------------------------------------------------------------


def test_delivery_decreases_finished_goods_stock(db_session, organisation, widget_product, warehouse_1):
    _receive(db_session, organisation, widget_product, warehouse_1, "100", reference_id=1)
    movement = _issue(db_session, organisation, widget_product, warehouse_1, "30", reference_id=2)
    db_session.commit()

    assert movement.movement_type == DELIVERY
    assert movement.quantity == Decimal("-30")
    assert _on_hand(db_session, widget_product, warehouse_1) == Decimal("70")


# --- 4. Negative stock is rejected ------------------------------------------------------------------


def test_delivery_exceeding_stock_on_hand_is_rejected(db_session, organisation, widget_product, warehouse_1):
    _receive(db_session, organisation, widget_product, warehouse_1, "10", reference_id=1)
    db_session.commit()

    with pytest.raises(BusinessRuleError, match="negative"):
        _issue(db_session, organisation, widget_product, warehouse_1, "11", reference_id=2)

    db_session.rollback()
    fresh = SessionLocal()
    try:
        assert _on_hand(fresh, widget_product, warehouse_1) == Decimal("10")
        assert fresh.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.movement_type == DELIVERY).count() == 0
    finally:
        fresh.close()


def test_delivery_with_nothing_on_hand_is_rejected(db_session, organisation, widget_product, warehouse_1):
    with pytest.raises(BusinessRuleError, match="negative"):
        _issue(db_session, organisation, widget_product, warehouse_1, "1", reference_id=1)

    db_session.rollback()
    fresh = SessionLocal()
    try:
        assert fresh.query(FinishedGoodsInventory).count() == 0
        assert fresh.query(FinishedGoodsMovement).count() == 0
    finally:
        fresh.close()


def test_negative_adjustment_that_would_go_negative_is_rejected(db_session, organisation, widget_product, warehouse_1):
    _receive(db_session, organisation, widget_product, warehouse_1, "10", reference_id=1)
    db_session.commit()

    with pytest.raises(BusinessRuleError, match="negative"):
        _adjust(db_session, organisation, widget_product, warehouse_1, "-11")

    db_session.rollback()
    fresh = SessionLocal()
    try:
        assert _on_hand(fresh, widget_product, warehouse_1) == Decimal("10")
    finally:
        fresh.close()


# --- 5. Duplicate source transactions cannot double-apply -----------------------------------------


def test_the_same_source_cannot_post_the_same_movement_type_twice(db_session, organisation, widget_product, warehouse_1):
    _receive(db_session, organisation, widget_product, warehouse_1, "100", reference_id=1)
    db_session.commit()

    with pytest.raises(ConflictError):
        _receive(db_session, organisation, widget_product, warehouse_1, "100", reference_id=1)

    db_session.rollback()
    fresh = SessionLocal()
    try:
        # Still only 100 -- the duplicate never applied a second time.
        assert _on_hand(fresh, widget_product, warehouse_1) == Decimal("100")
        assert fresh.query(FinishedGoodsMovement).count() == 1
    finally:
        fresh.close()


def test_a_delivery_can_reuse_a_receipts_reference_id_since_movement_type_differs(
    db_session, organisation, widget_product, warehouse_1
):
    """The duplicate guard is (reference_type, reference_id,
    movement_type) together -- a PRODUCTION_COMPLETION and a DELIVERY
    sharing the same source reference_id is not a duplicate, since
    they're different kinds of movement (mirrors how a RECEIPT and its
    later RECEIPT_REVERSAL share a reference in Raw Material Inventory)."""
    _receive(db_session, organisation, widget_product, warehouse_1, "100", reference_id=1)
    _issue(db_session, organisation, widget_product, warehouse_1, "20", reference_id=1)
    db_session.commit()

    assert _on_hand(db_session, widget_product, warehouse_1) == Decimal("80")


# --- 6. Ledger and balance remain atomic -----------------------------------------------------------


def test_ledger_and_balance_agree_after_several_movements(db_session, organisation, widget_product, warehouse_1):
    _receive(db_session, organisation, widget_product, warehouse_1, "100", reference_id=1)
    _issue(db_session, organisation, widget_product, warehouse_1, "15", reference_id=2)
    _adjust(db_session, organisation, widget_product, warehouse_1, "5")
    _adjust(db_session, organisation, widget_product, warehouse_1, "-3")
    db_session.commit()

    assert _on_hand(db_session, widget_product, warehouse_1) == _ledger_sum(db_session, widget_product, warehouse_1)
    assert _on_hand(db_session, widget_product, warehouse_1) == Decimal("87")


def test_a_rejected_delivery_leaves_no_partial_ledger_or_balance_effect(db_session, organisation, widget_product, warehouse_1):
    """When _increment_inventory rejects a movement as negative, nothing
    about it -- not the ledger row, not the balance -- survives, even
    though the ledger row was already flushed inside the same
    transaction before the rejection was raised."""
    _receive(db_session, organisation, widget_product, warehouse_1, "10", reference_id=1)
    db_session.commit()

    with pytest.raises(BusinessRuleError):
        _issue(db_session, organisation, widget_product, warehouse_1, "999", reference_id=2)
    db_session.rollback()

    fresh = SessionLocal()
    try:
        assert _on_hand(fresh, widget_product, warehouse_1) == Decimal("10")
        assert fresh.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.reference_id == 2).count() == 0
    finally:
        fresh.close()


# --- 7. A movement can never be edited/deleted -----------------------------------------------------


def test_finished_goods_movement_model_has_no_update_timestamp_or_edit_path(db_session, organisation, widget_product, warehouse_1):
    """FinishedGoodsMovement has no updated_at column at all (unlike
    FinishedGoodsInventory's own TimestampMixin) -- a movement is a
    historical fact, not a record with a lifecycle. There is also no
    service function anywhere that updates or deletes a
    FinishedGoodsMovement row; correcting one is always a new, opposite
    ADJUSTMENT movement (test below)."""
    movement = _receive(db_session, organisation, widget_product, warehouse_1, "100")
    db_session.commit()

    assert not hasattr(movement, "updated_at")
    assert finished_goods_inventory_service.__dict__.get("update_movement") is None
    assert finished_goods_inventory_service.__dict__.get("delete_movement") is None


def test_correcting_a_movement_is_a_new_opposite_adjustment_not_an_edit(db_session, organisation, widget_product, warehouse_1):
    original = _receive(db_session, organisation, widget_product, warehouse_1, "100", reference_id=1)
    correction = _adjust(db_session, organisation, widget_product, warehouse_1, "-20", reason="Original count was wrong")
    db_session.commit()

    fresh = SessionLocal()
    try:
        stored_original = fresh.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.id == original.id).one()
        assert stored_original.quantity == Decimal("100")  # untouched
        assert stored_original.movement_type == PRODUCTION_COMPLETION
        stored_correction = fresh.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.id == correction.id).one()
        assert stored_correction.quantity == Decimal("-20")
        assert stored_correction.movement_type == ADJUSTMENT
        assert fresh.query(FinishedGoodsMovement).count() == 2
        assert _on_hand(fresh, widget_product, warehouse_1) == Decimal("80")
    finally:
        fresh.close()


# --- adjustment reason / UOM ------------------------------------------------------------------------


def test_adjustment_writes_a_finished_goods_adjustment_row_with_the_reason(db_session, organisation, widget_product, warehouse_1):
    _receive(db_session, organisation, widget_product, warehouse_1, "50", reference_id=1)
    movement = _adjust(db_session, organisation, widget_product, warehouse_1, "5", reason="Cycle count correction")
    db_session.commit()

    assert movement.movement_type == ADJUSTMENT
    assert movement.reference_type == ADJUSTMENT_REFERENCE
    reason_row = db_session.query(FinishedGoodsAdjustment).filter(FinishedGoodsAdjustment.id == movement.reference_id).one()
    assert reason_row.reason == "Cycle count correction"


def test_movements_record_the_products_own_unit_of_measure(db_session, organisation, widget_product, warehouse_1):
    movement = _receive(db_session, organisation, widget_product, warehouse_1, "100")
    db_session.commit()
    assert movement.unit_of_measure_id == widget_product.unit_of_measure_id


# --- movement history / resulting balance -----------------------------------------------------------


def test_movement_history_resulting_balance_reconciles_with_the_stored_balance(
    db_session, organisation, widget_product, warehouse_1
):
    _receive(db_session, organisation, widget_product, warehouse_1, "100", reference_id=1)
    _issue(db_session, organisation, widget_product, warehouse_1, "10", reference_id=2)
    _adjust(db_session, organisation, widget_product, warehouse_1, "3")
    db_session.commit()

    entries = finished_goods_inventory_service.get_movement_history(
        db_session, product_id=widget_product.id, warehouse_id=warehouse_1.id
    )
    # Newest first.
    assert [e.movement.movement_type for e in entries] == [ADJUSTMENT, DELIVERY, PRODUCTION_COMPLETION]
    # The most recent entry's own resulting_balance is the current balance.
    assert entries[0].resulting_balance == _on_hand(db_session, widget_product, warehouse_1) == Decimal("93")
    # And the running balance is internally consistent at every step.
    assert entries[1].resulting_balance == Decimal("90")
    assert entries[2].resulting_balance == Decimal("100")


def test_stock_position_listing_reflects_the_current_balance(db_session, organisation, widget_product, warehouse_1):
    _receive(db_session, organisation, widget_product, warehouse_1, "42")
    db_session.commit()

    positions = finished_goods_inventory_service.list_stock_positions(db_session, organisation_id=organisation.id)
    assert len(positions) == 1
    assert positions[0].product_id == widget_product.id
    assert positions[0].warehouse_id == warehouse_1.id
    assert positions[0].quantity_on_hand == Decimal("42")
