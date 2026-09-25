"""Tests for Controlled Stock Adjustments (docs/modules/purchase_orders.md's
own "reversal, never edit" correction model, extended to a verified
physical/system stock difference that has no prior movement to
reverse): only an explicit inventory:adjust grant (or admin/super_admin)
may create one, a blank reason is rejected at the request boundary, and
the created adjustment is a normal, atomic, append-only StockMovement --
proven end to end through the HTTP API, complementing
test_inventory_service.py's direct service-level coverage."""
from decimal import Decimal

import pytest

from app.core.roles import TEAM_MEMBER
from app.models.inventory import ADJUSTMENT, InventoryAdjustment, RawMaterialInventory, StockMovement
from app.models.role_permission import RolePermission

ADJUSTMENTS_URL = "/api/inventory/adjustments"


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _adjust(client, headers, raw_material_id, warehouse_id, quantity, reason="Cycle count correction"):
    return client.post(
        ADJUSTMENTS_URL,
        json={"raw_material_id": raw_material_id, "warehouse_id": warehouse_id, "quantity": quantity, "reason": reason},
        headers=headers,
    )


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


def test_unauthorized_user_cannot_create_an_adjustment(
    client, team_member_headers, cement_raw_material, warehouse_1, db_session, organisation
):
    """A plain team member, granted nothing, is denied."""
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")
    response = _adjust(client, team_member_headers, cement_raw_material.id, warehouse_1.id, "5")
    assert response.status_code == 403


def test_warehouse_receiving_permission_alone_does_not_allow_adjustment(
    client, team_member_headers, active_user, organisation, cement_raw_material, warehouse_1, db_session
):
    """The gap-fix's own rule: `purchase:receive` is a different
    module_key than `inventory:adjust` -- granting the former must never
    also grant the latter."""
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase", action="receive", scope="all")
    )
    db_session.commit()

    response = _adjust(client, team_member_headers, cement_raw_material.id, warehouse_1.id, "5")
    assert response.status_code == 403


def test_team_member_granted_inventory_adjust_can_create_an_adjustment(
    client, team_member_headers, active_user, organisation, cement_raw_material, warehouse_1, db_session
):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="adjust", scope="all")
    )
    db_session.commit()

    response = _adjust(client, team_member_headers, cement_raw_material.id, warehouse_1.id, "5")
    assert response.status_code == 201


def test_admin_can_create_an_adjustment_without_any_explicit_grant(
    client, admin_headers, organisation, cement_raw_material, warehouse_1, db_session
):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")
    response = _adjust(client, admin_headers, cement_raw_material.id, warehouse_1.id, "5")
    assert response.status_code == 201


# --- request validation --------------------------------------------------------------------------


def test_adjustment_without_a_reason_is_rejected(
    client, admin_headers, organisation, cement_raw_material, warehouse_1, db_session
):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")
    response = _adjust(client, admin_headers, cement_raw_material.id, warehouse_1.id, "5", reason="")
    assert response.status_code == 422

    response = _adjust(client, admin_headers, cement_raw_material.id, warehouse_1.id, "5", reason="   ")
    assert response.status_code == 422

    assert db_session.query(StockMovement).filter(StockMovement.movement_type == ADJUSTMENT).count() == 0


def test_zero_adjustment_quantity_is_rejected(client, admin_headers, organisation, cement_raw_material, warehouse_1, db_session):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")
    response = _adjust(client, admin_headers, cement_raw_material.id, warehouse_1.id, "0")
    assert response.status_code == 422


def test_negative_adjustment_that_would_go_negative_is_rejected_with_a_clear_error(
    client, admin_headers, organisation, cement_raw_material, warehouse_1, db_session
):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "10")
    response = _adjust(client, admin_headers, cement_raw_material.id, warehouse_1.id, "-11")
    assert response.status_code == 400
    assert "negative" in response.json()["error"]["message"].lower()

    row = (
        db_session.query(RawMaterialInventory)
        .filter(RawMaterialInventory.raw_material_id == cement_raw_material.id, RawMaterialInventory.warehouse_id == warehouse_1.id)
        .first()
    )
    assert row.quantity_on_hand == Decimal("10.0000")


# --- end to end -------------------------------------------------------------------------------


def test_positive_adjustment_end_to_end(client, admin_headers, admin_user, organisation, cement_raw_material, warehouse_1, db_session):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")

    response = _adjust(client, admin_headers, cement_raw_material.id, warehouse_1.id, "8", reason="Physical count was higher")
    assert response.status_code == 201
    body = response.json()
    assert body["quantity"] == "8.0000"
    assert body["reason"] == "Physical count was higher"
    assert body["quantity_on_hand"] == "58.0000"
    assert body["created_by_name"] == admin_user.full_name
    assert body["raw_material_id"] == cement_raw_material.id
    assert body["warehouse_id"] == warehouse_1.id

    movement = db_session.query(StockMovement).filter(StockMovement.id == body["id"]).one()
    assert movement.movement_type == ADJUSTMENT
    assert movement.created_by_user_id == admin_user.id

    adjustment = db_session.query(InventoryAdjustment).filter(InventoryAdjustment.id == movement.reference_id).one()
    assert adjustment.reason == "Physical count was higher"


def test_negative_adjustment_end_to_end(client, admin_headers, organisation, cement_raw_material, warehouse_1, db_session):
    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")

    response = _adjust(client, admin_headers, cement_raw_material.id, warehouse_1.id, "-8", reason="Damaged stock written off")
    assert response.status_code == 201
    body = response.json()
    assert body["quantity"] == "-8.0000"
    assert body["quantity_on_hand"] == "42.0000"


def test_adjustment_rejects_an_inactive_or_cross_organisation_raw_material(
    client, admin_headers, organisation, other_organisation, cement_raw_material, warehouse_1, db_session
):
    from app.models.raw_material import RawMaterial

    _seed_stock(db_session, organisation, cement_raw_material, warehouse_1, "50")
    other_material = RawMaterial(
        organisation_id=other_organisation.id,
        code="OTHER",
        name="Other Org Material",
        category_id=cement_raw_material.category_id,
        unit_of_measure_id=cement_raw_material.unit_of_measure_id,
        is_active=True,
    )
    db_session.add(other_material)
    db_session.commit()

    response = _adjust(client, admin_headers, other_material.id, warehouse_1.id, "5")
    assert response.status_code == 422
