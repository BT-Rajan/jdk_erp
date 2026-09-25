"""Tests for the Inventory ledger hardening pass (gap-fix, no redesign):
every StockMovement records the unit its quantity is in, a source event
can never post the same kind of movement twice, no transaction can ever
leave RawMaterialInventory.quantity_on_hand negative, and a reversal is
always validated against -- and derives its material/warehouse/unit
from -- the original movement it targets, never from caller-supplied
values. Direct service-level tests (not through the PO/receipt HTTP
flow, which has its own coverage in test_purchase_order_receipts.py) so
the guards are proven at the one place they're supposed to hold:
inventory_service itself, independent of any particular caller's own
discipline."""
from decimal import Decimal

import pytest

from app.core.errors import BusinessRuleError, ConflictError
from app.models.inventory import RECEIPT, RECEIPT_REVERSAL, RawMaterialInventory, StockMovement
from app.services import inventory_service

REFERENCE_TYPE = "test_reference"


def _receive(db_session, organisation, cement_raw_material, warehouse_1, quantity, reference_id=1):
    return inventory_service.receive_stock(
        db_session,
        organisation_id=organisation.id,
        raw_material_id=cement_raw_material.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal(quantity),
        unit_of_measure_id=cement_raw_material.unit_of_measure_id,
        reference_type=REFERENCE_TYPE,
        reference_id=reference_id,
        created_by_user_id=None,
    )


def _reverse(db_session, organisation, cement_raw_material, warehouse_1, quantity, reference_id=1):
    return inventory_service.reverse_stock(
        db_session,
        organisation_id=organisation.id,
        quantity=Decimal(quantity),
        reference_type=REFERENCE_TYPE,
        reference_id=reference_id,
        created_by_user_id=None,
    )


def _on_hand(db_session, cement_raw_material, warehouse_1) -> Decimal:
    row = (
        db_session.query(RawMaterialInventory)
        .filter(
            RawMaterialInventory.raw_material_id == cement_raw_material.id,
            RawMaterialInventory.warehouse_id == warehouse_1.id,
        )
        .first()
    )
    return row.quantity_on_hand if row is not None else Decimal("0")


# --- movement UOM -----------------------------------------------------------------------------


def test_receive_stock_records_the_materials_own_unit(db_session, organisation, cement_raw_material, warehouse_1):
    movement = _receive(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()
    assert movement.unit_of_measure_id == cement_raw_material.unit_of_measure_id

    stored = db_session.query(StockMovement).filter(StockMovement.id == movement.id).one()
    assert stored.unit_of_measure_id == cement_raw_material.unit_of_measure_id
    assert stored.quantity == Decimal("100.0000")


def test_reverse_stock_records_the_same_unit(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()
    reversal = _reverse(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()
    assert reversal.unit_of_measure_id == cement_raw_material.unit_of_measure_id
    assert reversal.quantity == Decimal("-100.0000")


def test_reversal_derives_material_warehouse_and_unit_from_the_original_movement(
    db_session, organisation, cement_raw_material, warehouse_1
):
    """`reverse_stock` no longer takes raw_material_id/warehouse_id/
    unit_of_measure_id as caller-supplied arguments -- it looks up the
    original RECEIPT movement by reference and copies them from there,
    so a reversal can never target a different material/warehouse/unit
    than what it's actually offsetting."""
    original = _receive(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()
    reversal = _reverse(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()
    assert reversal.raw_material_id == original.raw_material_id
    assert reversal.warehouse_id == original.warehouse_id
    assert reversal.unit_of_measure_id == original.unit_of_measure_id


# --- duplicate protection ----------------------------------------------------------------------


def test_posting_the_same_source_movement_twice_is_rejected(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()

    with pytest.raises(ConflictError):
        _receive(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.rollback()

    assert db_session.query(StockMovement).filter(StockMovement.reference_type == REFERENCE_TYPE).count() == 1
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("100.0000")


def test_a_reversal_is_not_treated_as_a_duplicate_of_its_receipt(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()
    _reverse(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()

    movements = db_session.query(StockMovement).filter(StockMovement.reference_type == REFERENCE_TYPE).all()
    assert {(m.movement_type, m.quantity) for m in movements} == {
        (RECEIPT, Decimal("100.0000")),
        (RECEIPT_REVERSAL, Decimal("-100.0000")),
    }
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("0.0000")


def test_a_different_reference_id_is_not_a_duplicate(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100", reference_id=1)
    db_session.commit()
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "50", reference_id=2)
    db_session.commit()

    assert db_session.query(StockMovement).filter(StockMovement.reference_type == REFERENCE_TYPE).count() == 2
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("150.0000")


# --- negative stock protection ------------------------------------------------------------------
#
# Reversal is now capped at its original movement's own quantity (see
# "reversal integrity" below), and every original RECEIPT quantity is
# itself positive -- so, with only RECEIPT/RECEIPT_REVERSAL movement
# types existing in this pass, a valid reversal can no longer drive a
# (material, warehouse) pair negative: it can never take back more than
# that same original movement put in. That makes negative-stock
# protection unreachable *through* reverse_stock's own validation, but
# the guard is still the thing actually holding the invariant, and any
# future movement type (Production consumption, a manual adjustment)
# will rely on it -- so these tests exercise it directly at
# `_increment_inventory`, the one place quantity_on_hand is ever
# written, same as the rest of this file exercises inventory_service's
# internals directly rather than only through its public callers.


def test_a_transaction_that_would_go_negative_is_rejected_atomically(
    db_session, organisation, cement_raw_material, warehouse_1
):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "40", reference_id=1)
    db_session.commit()

    with pytest.raises(BusinessRuleError):
        inventory_service._increment_inventory(
            db_session,
            organisation_id=organisation.id,
            raw_material_id=cement_raw_material.id,
            warehouse_id=warehouse_1.id,
            quantity=Decimal("-100"),
        )
    db_session.rollback()

    # Nothing from the failed transaction survives -- the balance is
    # unchanged.
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("40.0000")


def test_negative_stock_is_rejected_not_clamped_to_zero(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "40", reference_id=1)
    db_session.commit()

    with pytest.raises(BusinessRuleError, match="negative"):
        inventory_service._increment_inventory(
            db_session,
            organisation_id=organisation.id,
            raw_material_id=cement_raw_material.id,
            warehouse_id=warehouse_1.id,
            quantity=Decimal("-41"),
        )
    db_session.rollback()

    # Still 40 -- never silently clamped to 0.
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("40.0000")


def test_first_ever_movement_for_a_material_cannot_be_negative(db_session, organisation, cement_raw_material, warehouse_1):
    """No RawMaterialInventory row exists yet -- a negative first
    movement must still be rejected, not silently create a negative
    snapshot."""
    with pytest.raises(BusinessRuleError, match="negative"):
        inventory_service._increment_inventory(
            db_session,
            organisation_id=organisation.id,
            raw_material_id=cement_raw_material.id,
            warehouse_id=warehouse_1.id,
            quantity=Decimal("-10"),
        )
    db_session.rollback()

    assert (
        db_session.query(RawMaterialInventory)
        .filter(
            RawMaterialInventory.raw_material_id == cement_raw_material.id,
            RawMaterialInventory.warehouse_id == warehouse_1.id,
        )
        .first()
        is None
    )


# --- reversal integrity --------------------------------------------------------------------------


def test_reversal_cannot_exceed_the_original_movements_quantity(
    db_session, organisation, cement_raw_material, warehouse_1
):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "40", reference_id=1)
    db_session.commit()

    with pytest.raises(BusinessRuleError):
        _reverse(db_session, organisation, cement_raw_material, warehouse_1, "41", reference_id=1)
    db_session.rollback()

    # No reversal row was written, and the balance is unchanged.
    assert db_session.query(StockMovement).filter(
        StockMovement.reference_type == REFERENCE_TYPE, StockMovement.reference_id == 1
    ).count() == 1
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("40.0000")


def test_reversal_without_a_matching_receipt_is_rejected(db_session, organisation, cement_raw_material, warehouse_1):
    """No arbitrary/manual reversal without a valid source -- a
    reference with no original RECEIPT movement can't be reversed."""
    with pytest.raises(BusinessRuleError):
        _reverse(db_session, organisation, cement_raw_material, warehouse_1, "10", reference_id=999)
    db_session.rollback()

    assert db_session.query(StockMovement).count() == 0


def test_a_receipt_can_only_be_reversed_once(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "40", reference_id=1)
    db_session.commit()
    _reverse(db_session, organisation, cement_raw_material, warehouse_1, "40", reference_id=1)
    db_session.commit()

    with pytest.raises(ConflictError):
        _reverse(db_session, organisation, cement_raw_material, warehouse_1, "40", reference_id=1)
    db_session.rollback()

    assert db_session.query(StockMovement).filter(StockMovement.reference_type == REFERENCE_TYPE).count() == 2
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("0.0000")
