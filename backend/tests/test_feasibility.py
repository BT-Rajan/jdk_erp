"""Sales S7: the 0-2 working-day feasibility calculation -- FG, then raw
materials (active BOM), production time (lead time vs working days),
manpower (Admin-set staff), machine (single machine, always available);
stops at the first failure and never changes stock."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.timezone import JDK_TIMEZONE
from app.models.bom import ACTIVE, Bom, BomComponent
from app.models.finished_goods_inventory import FinishedGoodsInventory, FinishedGoodsMovement
from app.models.inventory import RawMaterialInventory, StockMovement
from app.services import feasibility_service as fs
from app.services import finished_goods_inventory_service, inventory_service
from app.services.same_day_fg_service import RequestedQuantity

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)
WEDNESDAY = date(2026, 9, 30)  # 2 working days after Monday


@pytest.fixture()
def plant(db_session, organisation, widget_product, cement_raw_material, kilogram_unit, warehouse_1):
    """Widget: 10 kg FG on hand; 1 kg Widget needs 2 kg Cement (active
    BOM); 100 kg Cement on hand; lead time 2 days; needs 3 staff of the
    organisation's 5 per day."""
    bom = Bom(organisation_id=organisation.id, product_id=widget_product.id, base_quantity=Decimal("1"), status=ACTIVE)
    db_session.add(bom)
    db_session.flush()
    db_session.add(BomComponent(bom_id=bom.id, raw_material_id=cement_raw_material.id, quantity=Decimal("2")))
    widget_product.manufacturing_lead_time_days = 2
    widget_product.production_staff_required = 3
    organisation.production_staff_available_per_day = 5
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=widget_product.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("10"), unit_of_measure_id=kilogram_unit.id, reference_type="test_seed", reference_id=1,
        created_by_user_id=None,
    )
    inventory_service.receive_stock(
        db_session, organisation_id=organisation.id, raw_material_id=cement_raw_material.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("100"), unit_of_measure_id=kilogram_unit.id, reference_type="test_seed", reference_id=1,
        created_by_user_id=None,
    )
    db_session.commit()
    return organisation, widget_product, cement_raw_material


def _calc(db_session, organisation, product, quantity, requested=WEDNESDAY):
    return fs.calculate(
        db_session,
        organisation.id,
        requested,
        [RequestedQuantity(product.id, Decimal(quantity), product.unit_of_measure_id)],
        now=MONDAY_9AM_KUWAIT,
    )


def _statuses(result):
    return {stage.stage: stage.status for stage in result.stages}


def test_fg_sufficient_is_servable_without_checking_production(db_session, plant):
    organisation, widget, cement = plant
    result = _calc(db_session, organisation, widget, "10")
    assert (result.applies, result.delivery_window, result.decision) == (True, "within_2_working_days", "servable")
    assert result.reason_codes == [fs.FG_SUFFICIENT]
    assert _statuses(result) == {
        "finished_goods": "passed", "raw_materials": "not_reached", "production_time": "not_reached",
        "manpower": "not_reached", "machine": "not_reached",
    }


def test_shortfall_passes_every_stage_and_moves_no_stock(db_session, plant):
    organisation, widget, cement = plant
    before = (
        db_session.query(FinishedGoodsMovement).count(), db_session.query(StockMovement).count(),
        [r.quantity_on_hand for r in db_session.query(FinishedGoodsInventory).all()],
        [r.quantity_on_hand for r in db_session.query(RawMaterialInventory).all()],
    )
    # 30 requested, 10 in FG -> produce 20 -> 40 kg Cement of 100.
    result = _calc(db_session, organisation, widget, "30")
    assert result.decision == "servable"
    assert result.working_days_available == 2
    assert set(_statuses(result).values()) == {"shortfall", "passed"}
    assert result.reason_codes == [fs.MACHINE_ASSUMED_AVAILABLE]
    db_session.expire_all()
    after = (
        db_session.query(FinishedGoodsMovement).count(), db_session.query(StockMovement).count(),
        [r.quantity_on_hand for r in db_session.query(FinishedGoodsInventory).all()],
        [r.quantity_on_hand for r in db_session.query(RawMaterialInventory).all()],
    )
    assert after == before


def test_raw_material_or_bom_failure_stops_the_sequence(db_session, plant):
    organisation, widget, cement = plant
    # Produce 60 -> 120 kg Cement needed, only 100.
    short = _calc(db_session, organisation, widget, "70")
    assert (short.decision, short.failed_stage, short.reason_codes) == (
        "admin_override_required", "raw_materials", [fs.RAW_MATERIAL_SHORTAGE]
    )
    assert _statuses(short)["production_time"] == "not_reached"

    db_session.query(Bom).update({"status": "draft"})
    db_session.commit()
    no_bom = _calc(db_session, organisation, widget, "30")
    assert (no_bom.failed_stage, no_bom.reason_codes) == ("raw_materials", [fs.BOM_MISSING])


def test_production_time_and_manpower_failures(db_session, plant):
    organisation, widget, cement = plant
    widget.manufacturing_lead_time_days = 3  # > 2 working days available
    db_session.commit()
    slow = _calc(db_session, organisation, widget, "30")
    assert (slow.failed_stage, slow.reason_codes) == ("production_time", [fs.LEAD_TIME_EXCEEDS_WINDOW])
    assert _statuses(slow)["manpower"] == "not_reached"

    widget.manufacturing_lead_time_days = 2
    widget.production_staff_required = 6  # > 5 available
    db_session.commit()
    assert _calc(db_session, organisation, widget, "30").reason_codes == [fs.MANPOWER_INSUFFICIENT]

    organisation.production_staff_available_per_day = None
    db_session.commit()
    unset = _calc(db_session, organisation, widget, "30")
    assert (unset.failed_stage, unset.reason_codes) == ("manpower", [fs.MANPOWER_NOT_CONFIGURED])


def test_only_within_two_working_day_requests_are_calculated(db_session, plant):
    organisation, widget, cement = plant
    for requested, window in ((date(2026, 9, 28), "same_day"), (date(2026, 10, 1), "more_than_2_working_days"), (date(2026, 10, 2), "not_servable")):
        result = _calc(db_session, organisation, widget, "999", requested=requested)
        assert (result.applies, result.delivery_window, result.decision, result.stages) == (False, window, None, [])
