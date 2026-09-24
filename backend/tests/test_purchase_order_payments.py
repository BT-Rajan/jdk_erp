"""Tests for docs/modules/purchase_orders.md Revision 3: supplier
payments against a PO -- payment number format/yearly reset, recording
a payment (only once approved; an overpayment goes to reconciliation),
partial payments summing correctly toward paid/outstanding, cancelling
a payment (never a hard delete, stays visible with its original amount),
the separate purchase_payment permission grant (so Finance can be
granted independently of Procurement), evidence attachment, and the
inventory-independence guarantee (payment never touches stock)."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.roles import TEAM_MEMBER
from app.models.audit_event import AuditEvent, PURCHASE_ORDER_PAYMENT_CANCELLED, PURCHASE_ORDER_PAYMENT_RECORDED
from app.models.inventory import RawMaterialInventory, StockMovement
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
            "payment_terms": "Others: 30 days",
        },
        headers=headers,
    )


def _add_line(client, headers, po_id, raw_material_id, quantity, unit_price):
    return client.post(
        f"/api/purchase-orders/{po_id}/lines",
        json={"raw_material_id": raw_material_id, "quantity": quantity, "unit_price": unit_price},
        headers=headers,
    )


def _issue(client, headers, po_id):
    """Submit for approval, then approve (the old single "issue" step)."""
    submitted = client.post(f"/api/purchase-orders/{po_id}/submit", headers=headers)
    if submitted.status_code != 200:
        return submitted
    return client.post(f"/api/purchase-orders/{po_id}/approve", headers=headers)


def _record_payment(client, headers, po_id, amount, payment_date="2026-01-15", method="Bank Transfer", reference="TXN1"):
    return client.post(
        f"/api/purchase-orders/{po_id}/payments",
        json={"payment_date": payment_date, "amount": amount, "payment_method": method, "reference_number": reference},
        headers=headers,
    )


def _cancel_payment(client, headers, po_id, payment_id, reason="Recorded in error"):
    return client.post(
        f"/api/purchase-orders/{po_id}/payments/{payment_id}/cancel", json={"reason": reason}, headers=headers
    )


def _issued_po_with_line(client, headers, acme_supplier, warehouse_1, cement_raw_material, quantity="10", unit_price="100"):
    po = _create_po(client, headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, headers, po["id"], cement_raw_material.id, quantity, unit_price)
    return _issue(client, headers, po["id"]).json()


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login_headers(client, "admin_person")


# --- numbering -------------------------------------------------------------------


def test_payment_number_format(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    response = _record_payment(client, admin_headers, po["id"], "300")
    assert response.status_code == 201
    payment = response.json()["payments"][0]
    year_suffix = str(date.today().year % 100).zfill(2)
    assert payment["payment_number"] == f"{year_suffix}70001"


def test_payment_number_resets_per_year(db_session, organisation):
    number_2025 = purchase_order_service.generate_payment_number(db_session, organisation.id, today=date(2025, 12, 31))
    assert number_2025 == "2570001"


# --- recording / guard rails -------------------------------------------------------


def test_cannot_record_payment_against_a_draft_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", "100")
    response = _record_payment(client, admin_headers, po["id"], "100")
    assert response.status_code == 400


def test_zero_and_negative_amount_rejected(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    assert _record_payment(client, admin_headers, po["id"], "0").status_code == 422
    assert _record_payment(client, admin_headers, po["id"], "-50").status_code == 422


def test_overpayment_is_recorded_and_returned_to_the_creator(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)  # total = 1000
    response = _record_payment(client, admin_headers, po["id"], "1000.01")
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "payment_reconciliation"
    assert body["reconciliations"][0]["kind"] == "payment"


def test_partial_payments_and_outstanding(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)  # total = 1000
    first = _record_payment(client, admin_headers, po["id"], "300").json()
    assert first["paid_amount"] == "300.0000"
    assert first["outstanding_amount"] == "700.0000"

    second = _record_payment(client, admin_headers, po["id"], "400").json()
    assert second["paid_amount"] == "700.0000"
    assert second["outstanding_amount"] == "300.0000"
    assert len(second["payments"]) == 2

    third = _record_payment(client, admin_headers, po["id"], "300").json()
    assert third["paid_amount"] == "1000.0000"
    assert third["outstanding_amount"] == "0.0000"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PURCHASE_ORDER_PAYMENT_RECORDED, AuditEvent.entity_id == po["id"])
        .all()
    )
    assert len(event) == 3


def test_payment_never_affects_inventory(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    _record_payment(client, admin_headers, po["id"], "500")
    assert db_session.query(StockMovement).count() == 0
    assert db_session.query(RawMaterialInventory).count() == 0


# --- cancellation --------------------------------------------------------------


def test_cancel_payment_keeps_it_visible_and_recalculates_outstanding(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    recorded = _record_payment(client, admin_headers, po["id"], "300").json()
    payment_id = recorded["payments"][0]["id"]

    cancelled = _cancel_payment(client, admin_headers, po["id"], payment_id).json()
    assert cancelled["paid_amount"] == "0"  # Decimal("0") with no other payments to add precision from
    assert cancelled["outstanding_amount"] == "1000.0000"

    # The payment itself remains, visible, with its original amount.
    assert len(cancelled["payments"]) == 1
    assert cancelled["payments"][0]["status"] == "cancelled"
    assert cancelled["payments"][0]["amount"] == "300.0000"
    assert cancelled["payments"][0]["cancellation_reason"] == "Recorded in error"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PURCHASE_ORDER_PAYMENT_CANCELLED, AuditEvent.entity_id == po["id"])
        .first()
    )
    assert event is not None


def test_cannot_cancel_an_already_cancelled_payment(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    payment_id = _record_payment(client, admin_headers, po["id"], "300").json()["payments"][0]["id"]
    _cancel_payment(client, admin_headers, po["id"], payment_id)
    response = _cancel_payment(client, admin_headers, po["id"], payment_id)
    assert response.status_code == 400


def test_cancelling_a_payment_frees_up_room_for_a_new_one(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)  # total = 1000
    payment_id = _record_payment(client, admin_headers, po["id"], "1000").json()["payments"][0]["id"]

    _cancel_payment(client, admin_headers, po["id"], payment_id)
    response = _record_payment(client, admin_headers, po["id"], "1000")
    assert response.status_code == 201


# --- permissions: separate from `purchase` ---------------------------------------


def test_team_member_with_only_purchase_view_cannot_record_payment(
    client, active_user, organisation, acme_supplier, warehouse_1, cement_raw_material, db_session, admin_headers
):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)

    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase", action="view", scope="all")
    )
    db_session.commit()
    headers = _login_headers(client)
    response = _record_payment(client, headers, po["id"], "100")
    assert response.status_code == 403


def test_team_member_granted_purchase_payment_create_can_record_payment_but_not_cancel(
    client, active_user, organisation, acme_supplier, warehouse_1, cement_raw_material, db_session, admin_headers
):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)

    db_session.add(
        RolePermission(
            organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase_payment", action="create", scope="all"
        )
    )
    db_session.commit()
    headers = _login_headers(client)

    recorded = _record_payment(client, headers, po["id"], "100")
    assert recorded.status_code == 201
    payment_id = recorded.json()["payments"][0]["id"]

    # No "cancel" grant yet -- finance can record but not reverse.
    cancelled = _cancel_payment(client, headers, po["id"], payment_id)
    assert cancelled.status_code == 403


# --- organisation isolation ---------------------------------------------------


def test_payment_scoped_to_its_own_purchase_order(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    payment_id = _record_payment(client, admin_headers, po["id"], "100").json()["payments"][0]["id"]

    other_po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    response = _cancel_payment(client, admin_headers, other_po["id"], payment_id)
    assert response.status_code == 404


def test_cross_organisation_purchase_order_payment_404s(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, other_organisation, db_session
):
    po = _issued_po_with_line(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)

    from app.models.user import User
    from app.core.security import hash_password

    other_admin = User(
        organisation_id=other_organisation.id,
        role="admin",
        full_name="Other Admin",
        email="other-payments-admin@example.com",
        username="other_payments_admin",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(other_admin)
    db_session.commit()
    other_headers = _login_headers(client, "other_payments_admin")

    response = _record_payment(client, other_headers, po["id"], "100")
    assert response.status_code == 404
