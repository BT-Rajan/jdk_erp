"""Tests for docs/modules/purchase_orders.md Revision 4: Goods Receipt --
receipt numbering (YY9NNNN, yearly reset), the draft/posted/cancelled/
reversed lifecycle, zero inventory effect while draft, exactly-once
inventory effect on posting (including duplicate-post protection),
partial receipts across multiple receipt documents, over-receipt
rejection, reversal creating an offsetting movement while leaving the
original receipt visible and unchanged, traceability from a
StockMovement back to its receipt, and organisation isolation."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.roles import TEAM_MEMBER
from app.models.audit_event import (
    AuditEvent,
    PURCHASE_ORDER_RECEIPT_CANCELLED,
    PURCHASE_ORDER_RECEIPT_POSTED,
    PURCHASE_ORDER_RECEIPT_REVERSED,
)
from app.models.inventory import PURCHASE_ORDER_RECEIPT_LINE_REFERENCE, RawMaterialInventory, StockMovement
from app.models.role_permission import RolePermission
from app.services import purchase_order_service


FUTURE = (date.today() + timedelta(days=30)).isoformat()


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_po(client, headers, supplier_id, warehouse_id):
    return client.post(
        "/api/purchase-orders",
        json={
            "supplier_id": supplier_id, "warehouse_id": warehouse_id, "expected_delivery_date": FUTURE,
            "payment_terms": "30 days",
        },
        headers=headers,
    )


def _add_line(client, headers, po_id, raw_material_id, quantity, unit_price):
    return client.post(
        f"/api/purchase-orders/{po_id}/lines",
        json={"raw_material_id": raw_material_id, "quantity": quantity, "unit_price": unit_price},
        headers=headers,
    )


def _issue_and_confirm(client, headers, po_id):
    """Submit -> approve -> mark sent: the PO is now receivable."""
    client.post(f"/api/purchase-orders/{po_id}/submit", headers=headers)
    client.post(f"/api/purchase-orders/{po_id}/approve", headers=headers)
    return client.post(f"/api/purchase-orders/{po_id}/send", json={"email": False}, headers=headers)


def _create_receipt(client, headers, po_id, lines, receipt_date="2026-01-20", supplier_delivery_reference=None):
    return client.post(
        f"/api/purchase-orders/{po_id}/receipts",
        json={
            "receipt_date": receipt_date,
            "supplier_delivery_reference": supplier_delivery_reference,
            "lines": lines,
        },
        headers=headers,
    )


def _post_receipt(client, headers, po_id, receipt_id):
    return client.post(f"/api/purchase-orders/{po_id}/receipts/{receipt_id}/post", headers=headers)


def _cancel_receipt(client, headers, po_id, receipt_id):
    return client.post(f"/api/purchase-orders/{po_id}/receipts/{receipt_id}/cancel", headers=headers)


def _reverse_receipt(client, headers, po_id, receipt_id, reason="Wrong quantity recorded"):
    return client.post(
        f"/api/purchase-orders/{po_id}/receipts/{receipt_id}/reverse", json={"reason": reason}, headers=headers
    )


def _confirmed_po_with_line(client, headers, acme_supplier, warehouse_1, cement_raw_material, quantity="1000", unit_price="1"):
    po = _create_po(client, headers, acme_supplier.id, warehouse_1.id).json()
    line = _add_line(client, headers, po["id"], cement_raw_material.id, quantity, unit_price).json()["lines"][0]
    _issue_and_confirm(client, headers, po["id"])
    return po, line


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login_headers(client, "admin_person")


# --- numbering -------------------------------------------------------------------


def test_receipt_number_format(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    response = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}])
    assert response.status_code == 201
    receipt = response.json()["receipts"][0]
    year_suffix = str(date.today().year % 100).zfill(2)
    assert receipt["receipt_number"] == f"{year_suffix}90001"


def test_receipt_number_resets_per_year(db_session, organisation):
    number_2025 = purchase_order_service.generate_receipt_number(db_session, organisation.id, today=date(2025, 12, 31))
    assert number_2025 == "2590001"


# --- basic receipt / draft has zero inventory effect ------------------------------


def test_draft_receipt_has_zero_inventory_effect(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    response = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}])
    assert response.status_code == 201
    body = response.json()
    assert body["receipts"][0]["status"] == "draft"
    assert body["status"] == "sent"  # unchanged -- draft never touches the PO's own status
    assert body["lines"][0]["received_quantity"] == "0.0000"
    assert db_session.query(StockMovement).count() == 0
    assert db_session.query(RawMaterialInventory).count() == 0


def test_post_receipt_updates_inventory_and_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]

    response = _post_receipt(client, admin_headers, po["id"], receipt["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["receipts"][0]["status"] == "posted"
    assert body["status"] == "partially_received"
    assert body["lines"][0]["received_quantity"] == "600.0000"

    inventory = (
        db_session.query(RawMaterialInventory)
        .filter(RawMaterialInventory.raw_material_id == cement_raw_material.id, RawMaterialInventory.warehouse_id == warehouse_1.id)
        .first()
    )
    assert inventory.quantity_on_hand == Decimal("600.0000")

    movements = db_session.query(StockMovement).filter(StockMovement.reference_type == PURCHASE_ORDER_RECEIPT_LINE_REFERENCE).all()
    assert len(movements) == 1
    assert movements[0].quantity == Decimal("600.0000")

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PURCHASE_ORDER_RECEIPT_POSTED, AuditEvent.entity_id == po["id"])
        .first()
    )
    assert event is not None


def test_second_receipt_completes_the_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    first_receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]
    _post_receipt(client, admin_headers, po["id"], first_receipt["id"])

    second_receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "400"}]).json()["receipts"][-1]
    response = _post_receipt(client, admin_headers, po["id"], second_receipt["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["lines"][0]["received_quantity"] == "1000.0000"

    db_session.expire_all()
    inventory = db_session.query(RawMaterialInventory).filter(RawMaterialInventory.raw_material_id == cement_raw_material.id).first()
    assert inventory.quantity_on_hand == Decimal("1000.0000")
    assert len(body["receipts"]) == 2


def test_po_remains_open_for_remaining_quantity_after_partial_receipt(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    first_receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]
    body = _post_receipt(client, admin_headers, po["id"], first_receipt["id"]).json()
    assert body["status"] == "partially_received"

    # Still receivable -- a second receipt against the remaining 400 succeeds.
    response = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "400"}])
    assert response.status_code == 201


# --- over-receipt ------------------------------------------------------------------


def test_over_receipt_rejected_at_draft_creation(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, quantity="1000")
    response = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "1000.01"}])
    assert response.status_code == 422
    assert db_session.query(StockMovement).count() == 0


def test_over_receipt_rejected_at_post_time_when_remaining_shrank_since_draft(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    """Two drafts are each individually valid against the 1000 ordered
    (600 each, drafted before either has posted) but together exceed it.
    The first posts fine; the second must be rejected at *posting* time,
    not merely at draft-creation time, proving post_receipt's own atomic
    guard is the authoritative one (docs/modules/purchase_orders.md #39)."""
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, quantity="1000")
    first_receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]
    second_receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][-1]

    assert _post_receipt(client, admin_headers, po["id"], first_receipt["id"]).status_code == 200

    response = _post_receipt(client, admin_headers, po["id"], second_receipt["id"])
    assert response.status_code == 409
    assert db_session.query(StockMovement).count() == 1


# --- duplicate posting --------------------------------------------------------------


def test_posting_the_same_receipt_twice_only_applies_inventory_once(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]

    first = _post_receipt(client, admin_headers, po["id"], receipt["id"])
    assert first.status_code == 200

    second = _post_receipt(client, admin_headers, po["id"], receipt["id"])
    assert second.status_code == 400

    db_session.expire_all()
    inventory = db_session.query(RawMaterialInventory).filter(RawMaterialInventory.raw_material_id == cement_raw_material.id).first()
    assert inventory.quantity_on_hand == Decimal("600.0000")
    assert db_session.query(StockMovement).count() == 1


# --- draft cancellation --------------------------------------------------------------


def test_cancel_draft_receipt_has_no_inventory_effect(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]

    response = _cancel_receipt(client, admin_headers, po["id"], receipt["id"])
    assert response.status_code == 200
    assert response.json()["receipts"][0]["status"] == "cancelled"
    assert db_session.query(StockMovement).count() == 0

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PURCHASE_ORDER_RECEIPT_CANCELLED, AuditEvent.entity_id == po["id"])
        .first()
    )
    assert event is not None


def test_cannot_post_a_cancelled_receipt(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]
    _cancel_receipt(client, admin_headers, po["id"], receipt["id"])

    response = _post_receipt(client, admin_headers, po["id"], receipt["id"])
    assert response.status_code == 400


# --- reversal ------------------------------------------------------------------


def test_reverse_posted_receipt_keeps_it_visible_and_reverts_inventory(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]
    _post_receipt(client, admin_headers, po["id"], receipt["id"])

    response = _reverse_receipt(client, admin_headers, po["id"], receipt["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sent"  # back to before any receipt, not partially_received
    assert body["lines"][0]["received_quantity"] == "0.0000"

    reversed_receipt = body["receipts"][0]
    assert reversed_receipt["status"] == "reversed"
    assert reversed_receipt["reversal_reason"] == "Wrong quantity recorded"
    # The original receipt line's own quantity is untouched -- it still
    # says 600, the physical fact that arrived; only the PO's derived
    # received_quantity and inventory were stepped back.
    assert reversed_receipt["lines"][0]["quantity"] == "600.0000"

    db_session.expire_all()
    inventory = db_session.query(RawMaterialInventory).filter(RawMaterialInventory.raw_material_id == cement_raw_material.id).first()
    assert inventory.quantity_on_hand == Decimal("0.0000")

    movements = db_session.query(StockMovement).order_by(StockMovement.id).all()
    assert len(movements) == 2
    assert movements[0].quantity == Decimal("600.0000")
    assert movements[1].quantity == Decimal("-600.0000")
    assert movements[1].movement_type == "receipt_reversal"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PURCHASE_ORDER_RECEIPT_REVERSED, AuditEvent.entity_id == po["id"])
        .first()
    )
    assert event is not None


def test_reverse_requires_a_reason(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]
    _post_receipt(client, admin_headers, po["id"], receipt["id"])

    response = client.post(
        f"/api/purchase-orders/{po['id']}/receipts/{receipt['id']}/reverse", json={"reason": ""}, headers=admin_headers
    )
    assert response.status_code == 422


def test_cannot_reverse_a_draft_receipt(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]

    response = _reverse_receipt(client, admin_headers, po["id"], receipt["id"])
    assert response.status_code == 400


def test_reversal_allows_a_fresh_correct_receipt(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "600"}]).json()["receipts"][0]
    _post_receipt(client, admin_headers, po["id"], receipt["id"])
    _reverse_receipt(client, admin_headers, po["id"], receipt["id"])

    corrected = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "550"}])
    assert corrected.status_code == 201
    posted = _post_receipt(client, admin_headers, po["id"], corrected.json()["receipts"][-1]["id"])
    assert posted.status_code == 200
    assert posted.json()["lines"][0]["received_quantity"] == "550.0000"


# --- guard rails: PO status --------------------------------------------------------


def test_cannot_create_a_receipt_against_an_unconfirmed_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    line = _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", "5").json()["lines"][0]
    client.post(f"/api/purchase-orders/{po['id']}/submit", headers=admin_headers)
    client.post(f"/api/purchase-orders/{po['id']}/approve", headers=admin_headers)  # approved, not yet sent

    response = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "10"}])
    assert response.status_code == 400


def test_cannot_create_a_receipt_with_a_line_from_another_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po_a, line_a = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    po_b, _ = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)

    response = _create_receipt(client, admin_headers, po_b["id"], [{"purchase_order_line_id": line_a["id"], "quantity": "10"}])
    assert response.status_code == 422


def test_zero_and_negative_receipt_quantity_rejected(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    zero = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "0"}])
    assert zero.status_code == 422
    negative = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "-5"}])
    assert negative.status_code == 422


# --- permissions ---------------------------------------------------------------


def test_receipt_requires_the_receive_permission(
    client, active_user, organisation, acme_supplier, warehouse_1, cement_raw_material, db_session, admin_headers
):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)

    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase", action="view", scope="all")
    )
    db_session.commit()
    headers = _login_headers(client)
    response = _create_receipt(client, headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "10"}])
    assert response.status_code == 403


# --- organisation isolation ---------------------------------------------------


def test_cross_organisation_receipt_404s(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, other_organisation, db_session
):
    po, line = _confirmed_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "10"}]).json()["receipts"][0]

    from app.core.security import hash_password
    from app.models.user import User

    other_admin = User(
        organisation_id=other_organisation.id,
        role="admin",
        full_name="Other Admin",
        email="other-receipts-admin@example.com",
        username="other_receipts_admin",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(other_admin)
    db_session.commit()
    other_headers = _login_headers(client, "other_receipts_admin")

    response = _post_receipt(client, other_headers, po["id"], receipt["id"])
    assert response.status_code == 404


def test_receipt_in_purchase_unit_posts_stock_in_material_unit(
    client, admin_headers, db_session, organisation, electronics_category, mass_kilogram_unit, acme_supplier, warehouse_1
):
    from app.models.raw_material import RawMaterial
    from app.models.unit import UnitOfMeasure

    tonne = UnitOfMeasure(organisation_id=organisation.id, name="Tonne", code="MT", dimension="mass", conversion_factor_to_base=1000, is_active=True)
    gravel = RawMaterial(organisation_id=organisation.id, code="RM9", name="Gravel", category_id=electronics_category.id, unit_of_measure_id=mass_kilogram_unit.id, is_active=True)
    db_session.add_all([tonne, gravel])
    db_session.commit()

    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    line = client.post(
        f"/api/purchase-orders/{po['id']}/lines",
        json={"raw_material_id": gravel.id, "quantity": "2", "unit_price": "85", "unit_of_measure_id": tonne.id},
        headers=admin_headers,
    ).json()["lines"][0]
    _issue_and_confirm(client, admin_headers, po["id"])
    receipt = _create_receipt(client, admin_headers, po["id"], [{"purchase_order_line_id": line["id"], "quantity": "2"}]).json()["receipts"][0]
    posted = _post_receipt(client, admin_headers, po["id"], receipt["id"])
    assert posted.status_code == 200, posted.text
    assert posted.json()["status"] == "received"

    stock = db_session.query(RawMaterialInventory).filter(RawMaterialInventory.raw_material_id == gravel.id).one()
    assert stock.quantity_on_hand == Decimal("2000.0000")
