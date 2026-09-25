"""Tests for the Finished Goods Inventory HTTP API
(app/api/finished_goods_inventory.py): the Stock Position and movement-
history GET endpoints require inventory:view (or admin), the Controlled
Finished Goods Stock Adjustment POST endpoint reuses inventory:adjust
unchanged from Raw Material Inventory, and a plain view grant never
also grants the authority to alter stock -- proven end to end through
the HTTP API, complementing test_finished_goods_inventory_service.py's
direct service-level coverage."""
from decimal import Decimal

import pytest

from app.core.roles import TEAM_MEMBER
from app.models.finished_goods_inventory import ADJUSTMENT, FinishedGoodsInventory, FinishedGoodsMovement
from app.models.role_permission import RolePermission
from app.services import finished_goods_inventory_service

STOCK_POSITIONS_URL = "/api/finished-goods-inventory"
MOVEMENTS_URL = "/api/finished-goods-inventory/movements"
ADJUSTMENTS_URL = "/api/finished-goods-inventory/adjustments"


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login_headers(client, "admin_person")


@pytest.fixture()
def team_member_headers(client, active_user):
    return _login_headers(client, "ada")


def _seed_stock(db_session, organisation, widget_product, warehouse_1, quantity, reference_id=1):
    finished_goods_inventory_service.receive_finished_goods(
        db_session,
        organisation_id=organisation.id,
        product_id=widget_product.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal(quantity),
        unit_of_measure_id=widget_product.unit_of_measure_id,
        reference_type="test_seed",
        reference_id=reference_id,
        created_by_user_id=None,
    )
    db_session.commit()


def _adjust(client, headers, product_id, warehouse_id, quantity, reason="Cycle count correction"):
    return client.post(
        ADJUSTMENTS_URL,
        json={"product_id": product_id, "warehouse_id": warehouse_id, "quantity": quantity, "reason": reason},
        headers=headers,
    )


# --- authorization: viewing ----------------------------------------------------------------------


def test_unauthorized_user_cannot_view_stock_positions(client, team_member_headers, db_session, organisation, widget_product, warehouse_1):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    response = client.get(STOCK_POSITIONS_URL, headers=team_member_headers)
    assert response.status_code == 403


def test_a_team_member_granted_inventory_view_can_view_stock_positions(
    client, team_member_headers, active_user, organisation, db_session, widget_product, warehouse_1
):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="view", scope="all")
    )
    db_session.commit()

    response = client.get(STOCK_POSITIONS_URL, headers=team_member_headers)
    assert response.status_code == 200


def test_inventory_adjust_alone_does_not_grant_viewing(
    client, team_member_headers, active_user, organisation, db_session, widget_product, warehouse_1
):
    """The rule 8 guarantee in the other direction: being able to alter
    stock must not, by itself, grant the ability to view it either --
    `adjust` and `view` are independent grants."""
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="adjust", scope="all")
    )
    db_session.commit()

    response = client.get(STOCK_POSITIONS_URL, headers=team_member_headers)
    assert response.status_code == 403


def test_admin_can_view_stock_positions_without_any_explicit_grant(client, admin_headers, organisation, db_session, widget_product, warehouse_1):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    response = client.get(STOCK_POSITIONS_URL, headers=admin_headers)
    assert response.status_code == 200


def test_unauthorized_user_cannot_view_movement_history(
    client, team_member_headers, db_session, organisation, widget_product, warehouse_1
):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    response = client.get(
        MOVEMENTS_URL, params={"product_id": widget_product.id, "warehouse_id": warehouse_1.id}, headers=team_member_headers
    )
    assert response.status_code == 403


# --- authorization: altering stock (view must not grant alter) -----------------------------------


def test_a_plain_view_grant_does_not_allow_creating_an_adjustment(
    client, team_member_headers, active_user, organisation, db_session, widget_product, warehouse_1
):
    """Rule 8's own core requirement: viewing stock must never come with
    the authority to alter it."""
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="view", scope="all")
    )
    db_session.commit()

    response = _adjust(client, team_member_headers, widget_product.id, warehouse_1.id, "5")
    assert response.status_code == 403


def test_purchase_receive_permission_alone_does_not_allow_a_finished_goods_adjustment(
    client, team_member_headers, active_user, organisation, db_session, widget_product, warehouse_1
):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase", action="receive", scope="all")
    )
    db_session.commit()

    response = _adjust(client, team_member_headers, widget_product.id, warehouse_1.id, "5")
    assert response.status_code == 403


def test_the_existing_raw_material_inventory_adjust_grant_also_covers_finished_goods(
    client, team_member_headers, active_user, organisation, db_session, widget_product, warehouse_1
):
    """This module's own explicit "reuse existing RBAC" instruction:
    the same inventory:adjust grant a Raw Material Adjustment already
    requires covers a Finished Goods Adjustment too -- no separate grant
    is invented."""
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="inventory", action="adjust", scope="all")
    )
    db_session.commit()

    response = _adjust(client, team_member_headers, widget_product.id, warehouse_1.id, "5")
    assert response.status_code == 201


def test_admin_can_create_an_adjustment_without_any_explicit_grant(client, admin_headers, organisation, db_session, widget_product, warehouse_1):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    response = _adjust(client, admin_headers, widget_product.id, warehouse_1.id, "5")
    assert response.status_code == 201


# --- stock position content -----------------------------------------------------------------------


def test_stock_position_shows_the_correct_balance_and_fields(client, admin_headers, organisation, db_session, widget_product, warehouse_1):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "77")

    response = client.get(STOCK_POSITIONS_URL, headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    row = body[0]
    assert row["product_id"] == widget_product.id
    assert row["product_code"] == widget_product.code
    assert row["warehouse_id"] == warehouse_1.id
    assert row["unit_of_measure_id"] == widget_product.unit_of_measure_id
    assert row["quantity_on_hand"] == "77.0000"
    assert row["status"] == "in_stock"


def test_stock_position_status_is_out_of_stock_at_zero(client, admin_headers, organisation, db_session, widget_product, warehouse_1):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10", reference_id=1)
    finished_goods_inventory_service.issue_finished_goods(
        db_session,
        organisation_id=organisation.id,
        product_id=widget_product.id,
        warehouse_id=warehouse_1.id,
        quantity=Decimal("10"),
        unit_of_measure_id=widget_product.unit_of_measure_id,
        reference_type="test_seed",
        reference_id=2,
        created_by_user_id=None,
    )
    db_session.commit()

    response = client.get(STOCK_POSITIONS_URL, headers=admin_headers)
    assert response.status_code == 200
    row = response.json()[0]
    assert row["quantity_on_hand"] == "0.0000"
    assert row["status"] == "out_of_stock"


def test_stock_position_list_is_empty_when_nothing_has_moved_yet(client, admin_headers):
    response = client.get(STOCK_POSITIONS_URL, headers=admin_headers)
    assert response.status_code == 200
    assert response.json() == []


# --- movement history reconciles with the stored balance -------------------------------------------


def test_movement_history_reconciles_with_the_stored_balance(client, admin_headers, organisation, db_session, widget_product, warehouse_1):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "100", reference_id=1)
    adjust_response = _adjust(client, admin_headers, widget_product.id, warehouse_1.id, "-15", reason="Damaged units written off")
    assert adjust_response.status_code == 201
    current_balance = Decimal(adjust_response.json()["quantity_on_hand"])

    response = client.get(
        MOVEMENTS_URL, params={"product_id": widget_product.id, "warehouse_id": warehouse_1.id}, headers=admin_headers
    )
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    # Newest first: the adjustment, then the original production completion.
    assert rows[0]["movement_type"] == ADJUSTMENT
    assert Decimal(rows[0]["resulting_balance"]) == current_balance == Decimal("85.0000")
    assert rows[1]["movement_type"] == "production_completion"
    assert Decimal(rows[1]["resulting_balance"]) == Decimal("100.0000")
    assert rows[0]["created_by_name"] == "Admin Person"


def test_movement_history_is_empty_for_a_pair_with_no_movements(client, admin_headers, widget_product, warehouse_1):
    response = client.get(
        MOVEMENTS_URL, params={"product_id": widget_product.id, "warehouse_id": warehouse_1.id}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json() == []


# --- request validation --------------------------------------------------------------------------


def test_adjustment_without_a_reason_is_rejected(client, admin_headers, organisation, db_session, widget_product, warehouse_1):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "50")
    response = _adjust(client, admin_headers, widget_product.id, warehouse_1.id, "5", reason="")
    assert response.status_code == 422
    assert db_session.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.movement_type == ADJUSTMENT).count() == 0


def test_zero_adjustment_quantity_is_rejected(client, admin_headers, organisation, db_session, widget_product, warehouse_1):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "50")
    response = _adjust(client, admin_headers, widget_product.id, warehouse_1.id, "0")
    assert response.status_code == 422


def test_negative_adjustment_that_would_go_negative_is_rejected_with_a_clear_error(
    client, admin_headers, organisation, db_session, widget_product, warehouse_1
):
    _seed_stock(db_session, organisation, widget_product, warehouse_1, "10")
    response = _adjust(client, admin_headers, widget_product.id, warehouse_1.id, "-11")
    assert response.status_code == 400
    assert "negative" in response.json()["error"]["message"].lower()

    row = (
        db_session.query(FinishedGoodsInventory)
        .filter(FinishedGoodsInventory.product_id == widget_product.id, FinishedGoodsInventory.warehouse_id == warehouse_1.id)
        .first()
    )
    assert row.quantity_on_hand == Decimal("10")
