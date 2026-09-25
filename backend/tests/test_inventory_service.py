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
from sqlalchemy import func

from app.core.database import SessionLocal
from app.core.errors import BusinessRuleError, ConflictError
from app.models.inventory import (
    ADJUSTMENT,
    ADJUSTMENT_REFERENCE,
    OPENING_STOCK,
    OPENING_STOCK_REFERENCE,
    RECEIPT,
    RECEIPT_REVERSAL,
    InventoryAdjustment,
    OpeningStockEntry,
    RawMaterialInventory,
    StockMovement,
)
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


def _adjust(db_session, organisation, cement_raw_material, warehouse_1, quantity, reason="Cycle count correction"):
    return inventory_service.adjust_stock(
        db_session,
        organisation_id=organisation.id,
        raw_material_id=cement_raw_material.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal(quantity),
        unit_of_measure_id=cement_raw_material.unit_of_measure_id,
        reason=reason,
        created_by_user_id=None,
    )


def _open_stock(db_session, organisation, cement_raw_material, warehouse_1, quantity, reason="Physical count at go-live"):
    return inventory_service.record_opening_stock(
        db_session,
        organisation_id=organisation.id,
        raw_material_id=cement_raw_material.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal(quantity),
        unit_of_measure_id=cement_raw_material.unit_of_measure_id,
        reason=reason,
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


def _ledger_sum(db_session, cement_raw_material, warehouse_1) -> Decimal:
    """The balance as the ledger itself implies it -- SUM(quantity) over
    every StockMovement for this (raw_material, warehouse) pair,
    independent of the RawMaterialInventory snapshot entirely. Used only
    to verify the snapshot agrees with the ledger it's derived from,
    never as a second way to compute a balance the app itself relies on."""
    total = (
        db_session.query(func.sum(StockMovement.quantity))
        .filter(
            StockMovement.raw_material_id == cement_raw_material.id,
            StockMovement.warehouse_id == warehouse_1.id,
        )
        .scalar()
    )
    return total if total is not None else Decimal("0")


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


# --- stock balance integrity ---------------------------------------------------------------------


def test_receipt_increases_balance_by_exactly_the_movements_quantity(
    db_session, organisation, cement_raw_material, warehouse_1
):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "40", reference_id=1)
    db_session.commit()
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("40.0000")

    _receive(db_session, organisation, cement_raw_material, warehouse_1, "15", reference_id=2)
    db_session.commit()
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("55.0000")


def test_reversal_decreases_balance_by_exactly_the_movements_quantity(
    db_session, organisation, cement_raw_material, warehouse_1
):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "40", reference_id=1)
    db_session.commit()

    _reverse(db_session, organisation, cement_raw_material, warehouse_1, "15", reference_id=1)
    db_session.commit()
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("25.0000")


def test_multiple_movements_produce_the_expected_cumulative_balance(
    db_session, organisation, cement_raw_material, warehouse_1
):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100", reference_id=1)
    db_session.commit()
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "50", reference_id=2)
    db_session.commit()
    _reverse(db_session, organisation, cement_raw_material, warehouse_1, "30", reference_id=1)
    db_session.commit()
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "20", reference_id=3)
    db_session.commit()

    # 100 + 50 - 30 + 20 = 140.
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("140.0000")


def test_ledger_derived_balance_matches_the_stored_snapshot(db_session, organisation, cement_raw_material, warehouse_1):
    """RawMaterialInventory.quantity_on_hand is only ever a materialized
    snapshot, never a second, independent source of truth -- summing
    StockMovement.quantity for this (material, warehouse) pair must
    always land on exactly what's stored, at every point along the way,
    not just at the end."""
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100", reference_id=1)
    db_session.commit()
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == _ledger_sum(db_session, cement_raw_material, warehouse_1)

    _receive(db_session, organisation, cement_raw_material, warehouse_1, "50", reference_id=2)
    db_session.commit()
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == _ledger_sum(db_session, cement_raw_material, warehouse_1)

    _reverse(db_session, organisation, cement_raw_material, warehouse_1, "30", reference_id=1)
    db_session.commit()
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == _ledger_sum(db_session, cement_raw_material, warehouse_1)


def test_a_row_created_by_another_session_between_this_ones_update_attempt_and_existence_check_is_not_wrongly_rejected(
    db_session, organisation, cement_raw_material, warehouse_1, monkeypatch
):
    """Concurrency: `_increment_inventory`'s conditional UPDATE and its
    own follow-up "does a row exist" check (reached only when the update
    found no row) are two separate statements, not one atomic step -- a
    *different* session's own first-ever movement for this same pair can
    commit in between. That must still be treated as a race this session
    lost, retried against the row that now exists, never as proof this
    session's own quantity was negative.

    Simulated by monkeypatching `_apply_conditional_update` so its first
    call -- the one `_increment_inventory` makes before its own
    "does a row exist" check -- has the race's exact effect (another
    session's commit landing right after it returns) before returning
    the same False a real race would have produced; every later call
    (this fix's own retry) runs unpatched. Two real, separate SQLite
    connections can't be driven through this exact interleaving directly
    -- plain SQLite (no WAL here, deliberately; see the Stock Balance
    audit report) only allows one writer, so simulating the *outcome* of
    the race is what actually exercises the bug this guards against, not
    a literal thread race."""
    real_apply_conditional_update = inventory_service._apply_conditional_update
    calls = {"n": 0}

    def _apply_conditional_update_racing_another_session(db, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            return real_apply_conditional_update(db, **kwargs)
        other = SessionLocal()
        try:
            other.add(
                RawMaterialInventory(
                    organisation_id=organisation.id,
                    raw_material_id=cement_raw_material.id,
                    warehouse_id=warehouse_1.id,
                    quantity_on_hand=Decimal("40"),
                )
            )
            other.commit()
        finally:
            other.close()
        return False

    monkeypatch.setattr(inventory_service, "_apply_conditional_update", _apply_conditional_update_racing_another_session)

    inventory_service._increment_inventory(
        db_session,
        organisation_id=organisation.id,
        raw_material_id=cement_raw_material.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal("15"),
    )
    db_session.commit()
    assert calls["n"] == 2  # the race was hit, and the retry is what actually applied it
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("55.0000")


def test_two_sequential_movements_for_the_same_pair_do_not_lose_either_update(
    db_session, organisation, cement_raw_material, warehouse_1
):
    """Two separate sessions (simulating two separate requests) writing
    to the same (material, warehouse) pair, one right after the other,
    must both take effect -- the second session's own commit, based on
    its own fresh read of the row the first session just committed, must
    not silently overwrite the first session's contribution."""
    # db_session (this test's own fixture) may itself be holding an open
    # transaction from an earlier fixture's add()->commit()->refresh()
    # -- release it first so it can't block the two independent sessions
    # below under plain SQLite's single-writer locking (same reasoning
    # as the test above).
    db_session.rollback()

    first = SessionLocal()
    try:
        inventory_service._increment_inventory(
            first,
            organisation_id=organisation.id,
            raw_material_id=cement_raw_material.id,
            warehouse_id=warehouse_1.id,
            quantity=Decimal("40"),
        )
        first.commit()
    finally:
        first.close()

    second = SessionLocal()
    try:
        inventory_service._increment_inventory(
            second,
            organisation_id=organisation.id,
            raw_material_id=cement_raw_material.id,
            warehouse_id=warehouse_1.id,
            quantity=Decimal("10"),
        )
        second.commit()
    finally:
        second.close()

    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("50.0000")


# --- Controlled Stock Adjustments ------------------------------------------------------------------


def test_positive_adjustment_increases_balance(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()

    _adjust(db_session, organisation, cement_raw_material, warehouse_1, "5")
    db_session.commit()

    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("105.0000")


def test_negative_adjustment_decreases_balance(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()

    _adjust(db_session, organisation, cement_raw_material, warehouse_1, "-15")
    db_session.commit()

    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("85.0000")


def test_negative_adjustment_that_would_create_negative_stock_is_rejected(
    db_session, organisation, cement_raw_material, warehouse_1
):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "10")
    db_session.commit()

    with pytest.raises(BusinessRuleError, match="negative"):
        _adjust(db_session, organisation, cement_raw_material, warehouse_1, "-11")
    db_session.rollback()

    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("10.0000")


def test_adjustment_creates_an_append_only_ledger_entry_distinct_from_a_receipt(
    db_session, organisation, cement_raw_material, warehouse_1
):
    """Traceability: an adjustment must be clearly identifiable as an
    adjustment, never confusable with a receipt or reversal."""
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "50")
    db_session.commit()
    movement = _adjust(db_session, organisation, cement_raw_material, warehouse_1, "7")
    db_session.commit()

    assert movement.movement_type == ADJUSTMENT
    assert movement.reference_type == ADJUSTMENT_REFERENCE
    assert movement.quantity == Decimal("7.0000")
    assert movement.unit_of_measure_id == cement_raw_material.unit_of_measure_id

    stored = db_session.query(StockMovement).filter(StockMovement.id == movement.id).one()
    assert stored.movement_type == ADJUSTMENT
    all_types = {
        m.movement_type
        for m in db_session.query(StockMovement).filter(StockMovement.raw_material_id == cement_raw_material.id)
    }
    assert all_types == {RECEIPT, ADJUSTMENT}


def test_adjustment_records_user_time_and_reason_correctly(db_session, organisation, active_user, cement_raw_material, warehouse_1):
    movement = inventory_service.adjust_stock(
        db_session,
        organisation_id=organisation.id,
        raw_material_id=cement_raw_material.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal("12"),
        unit_of_measure_id=cement_raw_material.unit_of_measure_id,
        reason="Physical count found 12 more bags than the system showed",
        created_by_user_id=active_user.id,
    )
    db_session.commit()

    assert movement.created_by_user_id == active_user.id
    assert movement.created_at is not None

    adjustment = db_session.query(InventoryAdjustment).filter(InventoryAdjustment.id == movement.reference_id).one()
    assert adjustment.reason == "Physical count found 12 more bags than the system showed"
    assert adjustment.organisation_id == organisation.id


def test_existing_movements_remain_unchanged_after_an_adjustment(
    db_session, organisation, cement_raw_material, warehouse_1
):
    receipt = _receive(db_session, organisation, cement_raw_material, warehouse_1, "80", reference_id=1)
    db_session.commit()
    original_quantity = receipt.quantity
    original_created_at = receipt.created_at

    _adjust(db_session, organisation, cement_raw_material, warehouse_1, "-5")
    db_session.commit()

    reloaded_receipt = db_session.query(StockMovement).filter(StockMovement.id == receipt.id).one()
    assert reloaded_receipt.quantity == original_quantity
    assert reloaded_receipt.created_at == original_created_at
    assert reloaded_receipt.movement_type == RECEIPT


def test_a_failed_adjustment_leaves_ledger_and_balance_unchanged(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "20")
    db_session.commit()

    with pytest.raises(BusinessRuleError):
        _adjust(db_session, organisation, cement_raw_material, warehouse_1, "-100")
    db_session.rollback()

    assert db_session.query(StockMovement).filter(StockMovement.movement_type == ADJUSTMENT).count() == 0
    assert db_session.query(InventoryAdjustment).count() == 0
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("20.0000")


def test_adjustment_balance_matches_the_ledger_sum(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "60", reference_id=1)
    db_session.commit()
    _adjust(db_session, organisation, cement_raw_material, warehouse_1, "10")
    db_session.commit()
    _adjust(db_session, organisation, cement_raw_material, warehouse_1, "-25")
    db_session.commit()

    assert _on_hand(db_session, cement_raw_material, warehouse_1) == _ledger_sum(db_session, cement_raw_material, warehouse_1)
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("45.0000")


# --- Controlled Opening Stock ------------------------------------------------------------------


def test_valid_opening_stock_increases_balance(db_session, organisation, cement_raw_material, warehouse_1):
    _open_stock(db_session, organisation, cement_raw_material, warehouse_1, "250")
    db_session.commit()

    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("250.0000")


def test_opening_stock_creates_an_append_only_ledger_entry_distinct_from_other_movements(
    db_session, organisation, cement_raw_material, warehouse_1
):
    """Traceability: opening stock must be clearly identifiable as
    opening stock, never confusable with a receipt, reversal or
    adjustment."""
    movement = _open_stock(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()

    assert movement.movement_type == OPENING_STOCK
    assert movement.reference_type == OPENING_STOCK_REFERENCE
    assert movement.quantity == Decimal("100.0000")
    assert movement.unit_of_measure_id == cement_raw_material.unit_of_measure_id

    stored = db_session.query(StockMovement).filter(StockMovement.id == movement.id).one()
    assert stored.movement_type == OPENING_STOCK


def test_opening_stock_records_user_time_and_reason_correctly(
    db_session, organisation, active_user, cement_raw_material, warehouse_1
):
    movement = inventory_service.record_opening_stock(
        db_session,
        organisation_id=organisation.id,
        raw_material_id=cement_raw_material.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal("40"),
        unit_of_measure_id=cement_raw_material.unit_of_measure_id,
        reason="Verified physical count before go-live",
        created_by_user_id=active_user.id,
    )
    db_session.commit()

    assert movement.created_by_user_id == active_user.id
    assert movement.created_at is not None

    entry = db_session.query(OpeningStockEntry).filter(OpeningStockEntry.id == movement.reference_id).one()
    assert entry.reason == "Verified physical count before go-live"
    assert entry.organisation_id == organisation.id
    assert entry.raw_material_id == cement_raw_material.id
    assert entry.warehouse_id == warehouse_1.id


def test_a_second_opening_stock_for_the_same_pair_is_rejected_as_a_duplicate(
    db_session, organisation, cement_raw_material, warehouse_1
):
    """Sequentially, a second submission for the same pair is caught by
    the broader "must be first movement" guard (the first opening
    stock's own StockMovement now counts as an existing movement) before
    it ever reaches the OpeningStockEntry table's own uniqueness -- see
    test_a_genuine_race_between_two_opening_stock_submissions_still_only_applies_once
    below for the case where that deeper, DB-level guard is the one that
    actually fires."""
    _open_stock(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.commit()

    with pytest.raises(BusinessRuleError):
        _open_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")
    db_session.rollback()

    assert db_session.query(StockMovement).filter(StockMovement.movement_type == OPENING_STOCK).count() == 1
    assert db_session.query(OpeningStockEntry).count() == 1
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("100.0000")


def test_a_genuine_race_between_two_opening_stock_submissions_still_only_applies_once(
    db_session, organisation, cement_raw_material, warehouse_1, monkeypatch
):
    """The "must be first movement" guard (`_has_any_movement`) is a
    plain SELECT, not a DB constraint -- two concurrent submissions for a
    pair with no movements yet could both pass it before either commits.
    OpeningStockEntry's own UNIQUE(raw_material_id, warehouse_id) is what
    actually closes that race. Simulated the same way the Stock Balance
    audit's own concurrency regression test is: monkeypatching the guard
    so its first call has the race's exact effect (a *different* session's
    own opening stock committing right after it returns "no movement
    yet") before returning that same False a real race would have
    produced; the real check runs unpatched from then on."""
    real_has_any_movement = inventory_service._has_any_movement
    calls = {"n": 0}

    def _has_any_movement_racing_another_session(db, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            return real_has_any_movement(db, **kwargs)
        other = SessionLocal()
        try:
            inventory_service.record_opening_stock(
                other,
                organisation_id=organisation.id,
                raw_material_id=cement_raw_material.id,
                warehouse_id=warehouse_1.id,
                quantity=Decimal("40"),
                unit_of_measure_id=cement_raw_material.unit_of_measure_id,
                reason="Other session won the race",
                created_by_user_id=None,
            )
            other.commit()
        finally:
            other.close()
        return False

    monkeypatch.setattr(inventory_service, "_has_any_movement", _has_any_movement_racing_another_session)

    with pytest.raises(ConflictError):
        _open_stock(db_session, organisation, cement_raw_material, warehouse_1, "100")
    db_session.rollback()

    # 2, not 1: the patch is global, so the inner "other" session's own
    # call into record_opening_stock also goes through it once (and
    # correctly falls through to the real check, since by then calls["n"]
    # is already > 1) -- what matters is db_session's own single attempt
    # above raised ConflictError, not this internal bookkeeping detail.
    assert calls["n"] == 2
    assert db_session.query(StockMovement).filter(StockMovement.movement_type == OPENING_STOCK).count() == 1
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("40.0000")


def test_existing_movements_remain_unchanged_after_opening_stock(
    db_session, organisation, cement_raw_material, material_m_kg, warehouse_1
):
    """Recording opening stock for one (material, warehouse) pair must
    leave a completely unrelated pair's own existing receipt untouched.
    Uses two different materials in the same warehouse -- opening stock
    for `material_m_kg` (which has no movements yet) is unaffected by,
    and doesn't affect, `cement_raw_material`'s own prior receipt (opening
    stock is only ever valid for a pair with no movements yet, so the
    same pair as an existing receipt isn't a usable scenario here)."""
    receipt = _receive(db_session, organisation, cement_raw_material, warehouse_1, "30", reference_id=1)
    db_session.commit()
    original_quantity = receipt.quantity
    original_created_at = receipt.created_at

    _open_stock(db_session, organisation, material_m_kg, warehouse_1, "20")
    db_session.commit()

    reloaded_receipt = db_session.query(StockMovement).filter(StockMovement.id == receipt.id).one()
    assert reloaded_receipt.quantity == original_quantity
    assert reloaded_receipt.created_at == original_created_at
    assert reloaded_receipt.movement_type == RECEIPT
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("30.0000")


def test_a_failed_opening_stock_leaves_ledger_and_balance_unchanged(
    db_session, organisation, cement_raw_material, warehouse_1
):
    _open_stock(db_session, organisation, cement_raw_material, warehouse_1, "75")
    db_session.commit()

    with pytest.raises(BusinessRuleError):
        _open_stock(db_session, organisation, cement_raw_material, warehouse_1, "999")
    db_session.rollback()

    assert db_session.query(StockMovement).filter(StockMovement.movement_type == OPENING_STOCK).count() == 1
    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("75.0000")


# --- ledger/balance reconciliation -----------------------------------------------------------


def test_reconciliation_reports_a_match_for_a_consistent_pair(db_session, organisation, cement_raw_material, warehouse_1):
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100", reference_id=1)
    db_session.commit()
    _adjust(db_session, organisation, cement_raw_material, warehouse_1, "-10")
    db_session.commit()

    report = inventory_service.reconcile_balances(db_session, organisation_id=organisation.id)
    entry = next(p for p in report if p.raw_material_id == cement_raw_material.id and p.warehouse_id == warehouse_1.id)
    assert entry.matches is True
    assert entry.ledger_sum == Decimal("90.0000")
    assert entry.quantity_on_hand == Decimal("90.0000")
    assert entry.difference == Decimal("0.0000")


def test_reconciliation_detects_a_snapshot_that_disagrees_with_the_ledger(
    db_session, organisation, cement_raw_material, warehouse_1
):
    """A genuine data-integrity problem -- the snapshot has drifted from
    what the ledger itself sums to (simulated here the only way it could
    ever happen: something outside inventory_service writing to
    quantity_on_hand directly, which this whole gap-fix pass exists to
    catch, not to have caused)."""
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100", reference_id=1)
    db_session.commit()

    row = (
        db_session.query(RawMaterialInventory)
        .filter(RawMaterialInventory.raw_material_id == cement_raw_material.id, RawMaterialInventory.warehouse_id == warehouse_1.id)
        .first()
    )
    row.quantity_on_hand = Decimal("150")
    db_session.commit()

    report = inventory_service.reconcile_balances(db_session, organisation_id=organisation.id)
    entry = next(p for p in report if p.raw_material_id == cement_raw_material.id and p.warehouse_id == warehouse_1.id)
    assert entry.matches is False
    assert entry.ledger_sum == Decimal("100.0000")
    assert entry.quantity_on_hand == Decimal("150")
    assert entry.difference == Decimal("50")


def test_reconciliation_never_writes_anything(db_session, organisation, cement_raw_material, warehouse_1):
    """Read-only: running the report must not change the snapshot, the
    ledger, or anything else -- even when it finds a mismatch."""
    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100", reference_id=1)
    db_session.commit()
    row = (
        db_session.query(RawMaterialInventory)
        .filter(RawMaterialInventory.raw_material_id == cement_raw_material.id, RawMaterialInventory.warehouse_id == warehouse_1.id)
        .first()
    )
    row.quantity_on_hand = Decimal("999")
    db_session.commit()

    inventory_service.reconcile_balances(db_session, organisation_id=organisation.id)

    assert _on_hand(db_session, cement_raw_material, warehouse_1) == Decimal("999")
    assert db_session.query(StockMovement).count() == 1


def test_reconciliation_is_scoped_to_its_own_organisation(
    db_session, organisation, other_organisation, cement_raw_material, warehouse_1
):
    from app.models.category import Category
    from app.models.raw_material import RawMaterial
    from app.models.unit import UnitOfMeasure
    from app.models.warehouse import Warehouse

    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    other_category = Category(organisation_id=other_organisation.id, name="Materials", code="MAT", is_active=True)
    db_session.add(other_category)
    db_session.commit()
    other_material = RawMaterial(
        organisation_id=other_organisation.id,
        code="OTH001",
        name="Other Org Cement",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(other_material)
    db_session.commit()
    other_warehouse = Warehouse(
        organisation_id=other_organisation.id,
        code="OWH-001",
        name="Other Org Warehouse",
        total_usable_storage_area=1000,
        storage_area_unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(other_warehouse)
    db_session.commit()

    _receive(db_session, organisation, cement_raw_material, warehouse_1, "100", reference_id=1)
    db_session.commit()
    inventory_service.receive_stock(
        db_session,
        organisation_id=other_organisation.id,
        raw_material_id=other_material.id,
        warehouse_id=other_warehouse.id,
        quantity=Decimal("40"),
        unit_of_measure_id=other_unit.id,
        reference_type="test_seed",
        reference_id=1,
        created_by_user_id=None,
    )
    db_session.commit()

    report = inventory_service.reconcile_balances(db_session, organisation_id=organisation.id)
    assert {(p.raw_material_id, p.warehouse_id) for p in report} == {(cement_raw_material.id, warehouse_1.id)}
