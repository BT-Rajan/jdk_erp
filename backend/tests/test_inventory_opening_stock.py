"""Tests for Controlled Opening Stock: only an explicit inventory:opening_stock
grant (or admin/super_admin) may create one, quantity must be strictly
positive, a duplicate submission for the same (raw material, warehouse)
pair is rejected, and the created entry is a normal, atomic, append-only
StockMovement -- proven end to end through the HTTP API, complementing
test_inventory_service.py's direct service-level coverage."""
from decimal import Decimal

import pytest

from app.core.roles import TEAM_MEMBER
from app.models.inventory import OPENING_STOCK, OpeningStockEntry, RawMaterialInventory, StockMovement
from app.models.role_permission import RolePermission

OPENING_STOCK_URL = "/api/inventory/opening-stock"


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _open_stock(client, headers, raw_material_id, warehouse_id, quantity, reason="Physical count at go-live"):
    return client.post(
        OPENING_STOCK_URL,
        json={"raw_material_id": raw_material_id, "warehouse_id": warehouse_id, "quantity": quantity, "reason": reason},
        headers=headers,
    )


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login_headers(client, "admin_person")


@pytest.fixture()
def team_member_headers(client, active_user):
    return _login_headers(client, "ada")


# --- authorization -----------------------------------------------------------------------------


def test_unauthorized_user_cannot_create_opening_stock(client, team_member_headers, cement_raw_material, warehouse_1):
    """A plain team member, granted nothing, is denied."""
    response = _open_stock(client, team_member_headers, cement_raw_material.id, warehouse_1.id, "100")
    assert response.status_code == 403


def test_warehouse_receiving_permission_alone_does_not_allow_opening_stock(
    client, team_member_headers, active_user, organisation, cement_raw_material, warehouse_1, db_session
):
    """`purchase:receive` is a different module_key than
    `inventory:opening_stock` -- granting the former must never also
    grant the latter."""
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase", action="receive", scope="all")
    )
    db_session.commit()

    response = _open_stock(client, team_member_headers, cement_raw_material.id, warehouse_1.id, "100")
    assert response.status_code == 403


def test_inventory_adjust_grant_alone_does_not_allow_opening_stock(
    client, team_member_headers, active_user, organisation, cement_raw_material, warehouse_1, db_session
):
    """`adjust` and `opening_stock` are deliberately separate actions --
    a grant for one must not imply the other."""
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="adjust", scope="all")
    )
    db_session.commit()

    response = _open_stock(client, team_member_headers, cement_raw_material.id, warehouse_1.id, "100")
    assert response.status_code == 403


def test_team_member_granted_inventory_opening_stock_can_create_it(
    client, team_member_headers, active_user, organisation, cement_raw_material, warehouse_1, db_session
):
    db_session.add(
        RolePermission(
            organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="opening_stock", scope="all"
        )
    )
    db_session.commit()

    response = _open_stock(client, team_member_headers, cement_raw_material.id, warehouse_1.id, "100")
    assert response.status_code == 201


def test_admin_can_create_opening_stock_without_any_explicit_grant(client, admin_headers, cement_raw_material, warehouse_1):
    response = _open_stock(client, admin_headers, cement_raw_material.id, warehouse_1.id, "100")
    assert response.status_code == 201


# --- request validation --------------------------------------------------------------------------


def test_zero_opening_stock_quantity_is_rejected(client, admin_headers, cement_raw_material, warehouse_1):
    response = _open_stock(client, admin_headers, cement_raw_material.id, warehouse_1.id, "0")
    assert response.status_code == 422


def test_negative_opening_stock_quantity_is_rejected(client, admin_headers, cement_raw_material, warehouse_1, db_session):
    response = _open_stock(client, admin_headers, cement_raw_material.id, warehouse_1.id, "-50")
    assert response.status_code == 422

    assert db_session.query(StockMovement).filter(StockMovement.movement_type == OPENING_STOCK).count() == 0


def test_opening_stock_without_a_reason_is_rejected(client, admin_headers, cement_raw_material, warehouse_1, db_session):
    response = _open_stock(client, admin_headers, cement_raw_material.id, warehouse_1.id, "100", reason="")
    assert response.status_code == 422

    response = _open_stock(client, admin_headers, cement_raw_material.id, warehouse_1.id, "100", reason="   ")
    assert response.status_code == 422

    assert db_session.query(StockMovement).filter(StockMovement.movement_type == OPENING_STOCK).count() == 0


# --- duplicate protection -----------------------------------------------------------------------


def test_duplicate_opening_stock_submission_is_rejected(client, admin_headers, cement_raw_material, warehouse_1, db_session):
    first = _open_stock(client, admin_headers, cement_raw_material.id, warehouse_1.id, "100")
    assert first.status_code == 201

    second = _open_stock(client, admin_headers, cement_raw_material.id, warehouse_1.id, "50")
    assert second.status_code == 409

    assert db_session.query(StockMovement).filter(StockMovement.movement_type == OPENING_STOCK).count() == 1
    row = (
        db_session.query(RawMaterialInventory)
        .filter(RawMaterialInventory.raw_material_id == cement_raw_material.id, RawMaterialInventory.warehouse_id == warehouse_1.id)
        .first()
    )
    assert row.quantity_on_hand == Decimal("100.0000")


# --- end to end -------------------------------------------------------------------------------


def test_opening_stock_end_to_end(client, admin_headers, admin_user, cement_raw_material, warehouse_1, db_session):
    response = _open_stock(client, admin_headers, cement_raw_material.id, warehouse_1.id, "500", reason="Verified physical count")
    assert response.status_code == 201
    body = response.json()
    assert body["quantity"] == "500.0000"
    assert body["reason"] == "Verified physical count"
    assert body["quantity_on_hand"] == "500.0000"
    assert body["created_by_name"] == admin_user.full_name
    assert body["unit_of_measure_id"] == cement_raw_material.unit_of_measure_id
    assert body["raw_material_id"] == cement_raw_material.id
    assert body["warehouse_id"] == warehouse_1.id

    movement = db_session.query(StockMovement).filter(StockMovement.id == body["id"]).one()
    assert movement.movement_type == OPENING_STOCK
    assert movement.created_by_user_id == admin_user.id
    assert movement.unit_of_measure_id == cement_raw_material.unit_of_measure_id

    entry = db_session.query(OpeningStockEntry).filter(OpeningStockEntry.id == movement.reference_id).one()
    assert entry.reason == "Verified physical count"
    assert entry.raw_material_id == cement_raw_material.id
    assert entry.warehouse_id == warehouse_1.id


def test_opening_stock_rejects_an_inactive_or_cross_organisation_raw_material(
    client, admin_headers, organisation, other_organisation, cement_raw_material, warehouse_1, db_session
):
    from app.models.raw_material import RawMaterial

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

    response = _open_stock(client, admin_headers, other_material.id, warehouse_1.id, "100")
    assert response.status_code == 422
