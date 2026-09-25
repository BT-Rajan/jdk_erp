"""Tests for the ledger/balance reconciliation report (gap-fix: the
Stock Balance audit's own noted gap -- nothing previously checked, in
production, whether RawMaterialInventory.quantity_on_hand still agrees
with what StockMovement sums to). Read-only: proven here to report
correctly and to never itself change anything, gated by its own
inventory:reconcile action, complementing test_inventory_service.py's
direct service-level coverage of reconcile_balances/get_ledger_sum."""
from decimal import Decimal

import pytest

from app.core.roles import TEAM_MEMBER
from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.role_permission import RolePermission

RECONCILIATION_URL = "/api/inventory/reconciliation"


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login_headers(client, "admin_person")


@pytest.fixture()
def team_member_headers(client, active_user):
    return _login_headers(client, "ada")


def _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, quantity):
    from app.services import inventory_service

    inventory_service.receive_stock(
        db_session,
        organisation_id=organisation.id,
        raw_material_id=cement_raw_material.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal(quantity),
        unit_of_measure_id=cement_raw_material.unit_of_measure_id,
        reference_type="test_seed",
        reference_id=1,
        created_by_user_id=None,
    )
    db_session.commit()


# --- authorization -----------------------------------------------------------------------------


def test_unauthorized_user_cannot_view_reconciliation_report(client, team_member_headers):
    response = client.get(RECONCILIATION_URL, headers=team_member_headers)
    assert response.status_code == 403


def test_warehouse_receiving_permission_alone_does_not_allow_reconciliation_view(
    client, team_member_headers, active_user, organisation, db_session
):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase", action="receive", scope="all")
    )
    db_session.commit()

    response = client.get(RECONCILIATION_URL, headers=team_member_headers)
    assert response.status_code == 403


def test_inventory_adjust_grant_alone_does_not_allow_reconciliation_view(
    client, team_member_headers, active_user, organisation, db_session
):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="adjust", scope="all")
    )
    db_session.commit()

    response = client.get(RECONCILIATION_URL, headers=team_member_headers)
    assert response.status_code == 403


def test_team_member_granted_inventory_reconcile_can_view_the_report(
    client, team_member_headers, active_user, organisation, db_session
):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="reconcile", scope="all")
    )
    db_session.commit()

    response = client.get(RECONCILIATION_URL, headers=team_member_headers)
    assert response.status_code == 200


def test_admin_can_view_the_report_without_any_explicit_grant(client, admin_headers):
    response = client.get(RECONCILIATION_URL, headers=admin_headers)
    assert response.status_code == 200


# --- report content -----------------------------------------------------------------------------


def test_reconciliation_report_end_to_end(client, admin_headers, organisation, cement_raw_material, warehouse_1, db_session):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "100")

    response = client.get(RECONCILIATION_URL, headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["pairs_checked"] == 1
    assert body["mismatches_found"] == 0
    pair = body["pairs"][0]
    assert pair["raw_material_id"] == cement_raw_material.id
    assert pair["material_name"] == cement_raw_material.name
    assert pair["warehouse_id"] == warehouse_1.id
    assert pair["warehouse_name"] == warehouse_1.name
    assert pair["ledger_sum"] == "100.0000"
    assert pair["quantity_on_hand"] == "100.0000"
    assert pair["difference"] == "0.0000"
    assert pair["matches"] is True


def test_reconciliation_report_flags_a_real_mismatch(
    client, admin_headers, organisation, cement_raw_material, warehouse_1, db_session
):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "100")

    row = (
        db_session.query(RawMaterialInventory)
        .filter(RawMaterialInventory.raw_material_id == cement_raw_material.id, RawMaterialInventory.warehouse_id == warehouse_1.id)
        .first()
    )
    row.quantity_on_hand = Decimal("77")
    db_session.commit()

    response = client.get(RECONCILIATION_URL, headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["mismatches_found"] == 1
    pair = body["pairs"][0]
    assert pair["matches"] is False
    assert pair["ledger_sum"] == "100.0000"
    assert pair["quantity_on_hand"] == "77.0000"
    assert pair["difference"] == "-23.0000"


def test_reconciliation_report_is_read_only(
    client, admin_headers, organisation, cement_raw_material, warehouse_1, db_session
):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "100")

    response = client.get(RECONCILIATION_URL, headers=admin_headers)
    assert response.status_code == 200

    movement_count_before = db_session.query(StockMovement).count()
    row = (
        db_session.query(RawMaterialInventory)
        .filter(RawMaterialInventory.raw_material_id == cement_raw_material.id, RawMaterialInventory.warehouse_id == warehouse_1.id)
        .first()
    )
    assert row.quantity_on_hand == Decimal("100.0000")
    assert db_session.query(StockMovement).count() == movement_count_before


def test_reconciliation_report_is_empty_for_an_organisation_with_no_inventory(client, admin_headers):
    response = client.get(RECONCILIATION_URL, headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["pairs_checked"] == 0
    assert body["mismatches_found"] == 0
    assert body["pairs"] == []
