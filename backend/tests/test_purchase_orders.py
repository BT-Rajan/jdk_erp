"""Tests for docs/modules/purchase_orders.md: the Purchase Flow as a
controlled commercial document (Supplier -> Purchase Order -> Issue ->
Supplier Confirmation -> Goods Receipt -> Raw Material Inventory) -- draft
creation/line management, PO numbering (YY5NNNN, yearly reset), issuing
(the immutable revision snapshot + generated PDF), historical integrity
across renegotiation, supplier confirmation as a distinct event, sending
via the native email integration, every guard rail the task spec calls
out, organisation isolation, and the purchase permission engine's
admin-bypass/deny-by-default/explicit-grant behaviour. The Goods Receipt
workflow itself (Revision 4) has its own test file,
test_purchase_order_receipts.py."""
from datetime import date
from decimal import Decimal

import pytest

from app.core.roles import TEAM_MEMBER
from app.models.audit_event import (
    AuditEvent,
    PURCHASE_ORDER_ISSUED,
    PURCHASE_ORDER_SEND_FAILED,
    PURCHASE_ORDER_SUPPLIER_CONFIRMED,
)
from app.models.file import FileRecord
from app.models.purchase_order import PurchaseOrder
from app.models.role_permission import RolePermission
from app.services import purchase_order_service


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_po(client, headers, supplier_id, warehouse_id, order_date="2026-01-10", notes=None):
    return client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier_id, "warehouse_id": warehouse_id, "order_date": order_date, "notes": notes},
        headers=headers,
    )


def _add_line(client, headers, po_id, raw_material_id, quantity, unit_price=None):
    payload = {"raw_material_id": raw_material_id, "quantity": quantity}
    if unit_price is not None:
        payload["unit_price"] = unit_price
    return client.post(f"/api/purchase-orders/{po_id}/lines", json=payload, headers=headers)


def _issue(client, headers, po_id):
    return client.post(f"/api/purchase-orders/{po_id}/issue", headers=headers)


def _reopen(client, headers, po_id):
    return client.patch(f"/api/purchase-orders/{po_id}/status", json={"status": "draft"}, headers=headers)


def _confirm_supplier(client, headers, po_id, note=None, file_ids=None):
    return client.post(
        f"/api/purchase-orders/{po_id}/confirm-supplier",
        json={"note": note, "file_ids": file_ids or []},
        headers=headers,
    )


def _send(client, headers, po_id):
    return client.post(f"/api/purchase-orders/{po_id}/send", headers=headers)


def _cancel(client, headers, po_id, reason="Supplier out of stock"):
    return client.patch(
        f"/api/purchase-orders/{po_id}/status", json={"status": "cancelled", "cancel_reason": reason}, headers=headers
    )


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login_headers(client, "admin_person")


# --- authentication / authorization -----------------------------------------


def test_list_purchase_orders_requires_authentication(client):
    response = client.get("/api/purchase-orders")
    assert response.status_code == 401


def test_team_member_denied_by_default(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/purchase-orders", headers=headers)
    assert response.status_code == 403


def test_team_member_allowed_once_granted_role_permission(client, active_user, organisation, db_session):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase", action="view", scope="all")
    )
    db_session.commit()
    headers = _login_headers(client)
    response = client.get("/api/purchase-orders", headers=headers)
    assert response.status_code == 200


def test_team_member_cannot_create_without_grant(client, active_user, acme_supplier, warehouse_1):
    headers = _login_headers(client)
    response = _create_po(client, headers, acme_supplier.id, warehouse_1.id)
    assert response.status_code == 403


# --- numbering -----------------------------------------------------------------


def test_po_number_format_and_yearly_sequence(client, admin_headers, acme_supplier, warehouse_1):
    first = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    second = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    year_suffix = str(date.today().year % 100).zfill(2)
    assert first["po_number"] == f"{year_suffix}50001"
    assert second["po_number"] == f"{year_suffix}50002"
    assert len(first["po_number"]) == 7
    assert first["po_number"][2] == "5"


def test_po_number_resets_per_year(db_session, organisation):
    number_2025 = purchase_order_service.generate_po_number(db_session, organisation.id, today=date(2025, 12, 31))
    assert number_2025 == "2550001"


# --- draft creation / line management ---------------------------------------


def test_create_rejects_inactive_supplier(client, admin_headers, acme_supplier, warehouse_1, db_session):
    acme_supplier.is_active = False
    db_session.add(acme_supplier)
    db_session.commit()
    response = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id)
    assert response.status_code == 422


def test_add_line_defaults_unit_price_from_reference_cost(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    cement_raw_material.reference_cost = Decimal("12.5000")
    db_session.add(cement_raw_material)
    db_session.commit()

    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    response = _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10")
    assert response.status_code == 201
    line = response.json()["lines"][0]
    assert line["unit_price"] == "12.5000"
    assert line["line_total"] == "125.0000"


def test_add_line_requires_unit_price_when_no_reference_cost(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    response = _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10")
    assert response.status_code == 422


def test_lines_and_header_not_editable_once_issued(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    line = _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5").json()["lines"][0]
    _issue(client, admin_headers, po["id"])

    edit_line = client.patch(
        f"/api/purchase-orders/{po['id']}/lines/{line['id']}", json={"quantity": "20"}, headers=admin_headers
    )
    assert edit_line.status_code == 400

    edit_header = client.patch(f"/api/purchase-orders/{po['id']}", json={"notes": "changed"}, headers=admin_headers)
    assert edit_header.status_code == 400


# --- issue / revision lifecycle ------------------------------------------------


def test_cannot_issue_purchase_order_with_no_lines(client, admin_headers, acme_supplier, warehouse_1):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    response = _issue(client, admin_headers, po["id"])
    assert response.status_code == 400


def test_issue_creates_revision_one_with_pdf(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    response = _issue(client, admin_headers, po["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "issued"
    assert body["revision_number"] == 1
    assert len(body["revisions"]) == 1
    revision = body["revisions"][0]
    assert revision["revision_number"] == 1
    assert revision["total_amount"] == "50.0000"
    assert revision["pdf_file"] is not None
    assert revision["pdf_file"]["mime_type"] == "application/pdf"

    pdf_record = db_session.query(FileRecord).filter(FileRecord.id == revision["pdf_file"]["id"]).first()
    assert pdf_record.entity_type == "purchase_order_revision"

    event = (
        db_session.query(AuditEvent).filter(AuditEvent.action == PURCHASE_ORDER_ISSUED, AuditEvent.entity_id == po["id"]).first()
    )
    assert event is not None


def test_renegotiation_preserves_revision_one_unchanged(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    line = _add_line(client, admin_headers, po["id"], cement_raw_material.id, "100", unit_price="1.00").json()["lines"][0]
    _issue(client, admin_headers, po["id"])

    reopened = _reopen(client, admin_headers, po["id"])
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "draft"

    client.patch(f"/api/purchase-orders/{po['id']}/lines/{line['id']}", json={"unit_price": "0.95"}, headers=admin_headers)
    second_issue = _issue(client, admin_headers, po["id"])
    assert second_issue.status_code == 200
    body = second_issue.json()
    assert body["status"] == "issued"
    assert body["revision_number"] == 2
    assert body["po_number"] == po["po_number"]  # PO number never changes
    assert len(body["revisions"]) == 2

    revision_1 = next(r for r in body["revisions"] if r["revision_number"] == 1)
    revision_2 = next(r for r in body["revisions"] if r["revision_number"] == 2)
    assert revision_1["lines"][0]["unit_price"] == "1.0000"  # untouched by the later edit
    assert revision_2["lines"][0]["unit_price"] == "0.9500"


def test_cannot_reopen_a_draft_purchase_order(client, admin_headers, acme_supplier, warehouse_1):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    response = _reopen(client, admin_headers, po["id"])
    assert response.status_code == 400


# --- supplier confirmation ------------------------------------------------------


def test_cannot_confirm_supplier_before_issued(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    response = _confirm_supplier(client, admin_headers, po["id"])
    assert response.status_code == 400


def test_confirm_supplier_records_event_and_is_distinct_from_issuing(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    issued = _issue(client, admin_headers, po["id"]).json()
    assert issued["status"] == "issued"
    assert issued["supplier_confirmed_at"] is None  # issuing != confirming

    confirmed = _confirm_supplier(client, admin_headers, po["id"], note="Signed PO received").json()
    assert confirmed["status"] == "supplier_confirmed"
    assert confirmed["supplier_confirmed_at"] is not None
    assert confirmed["supplier_confirmation_note"] == "Signed PO received"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PURCHASE_ORDER_SUPPLIER_CONFIRMED, AuditEvent.entity_id == po["id"])
        .first()
    )
    assert event is not None


# --- sending ---------------------------------------------------------------------


def test_send_without_configured_mailbox_fails_and_is_recorded(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    acme_supplier.email = "supplier@example.com"
    db_session.add(acme_supplier)
    db_session.commit()

    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _issue(client, admin_headers, po["id"])

    response = _send(client, admin_headers, po["id"])
    assert response.status_code == 400  # BusinessRuleError -- no mailbox configured in tests

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PURCHASE_ORDER_SEND_FAILED, AuditEvent.entity_id == po["id"])
        .first()
    )
    assert event is not None
    assert event.result == "failure"

    # A failed send never flips the PO's own status.
    db_session.expire_all()
    po_row = db_session.query(PurchaseOrder).filter(PurchaseOrder.id == po["id"]).first()
    assert po_row.status == "issued"


def test_cannot_send_a_draft_purchase_order(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    response = _send(client, admin_headers, po["id"])
    assert response.status_code == 400


def test_send_rejects_supplier_with_no_email(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    acme_supplier.email = None
    db_session.add(acme_supplier)
    db_session.commit()
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _issue(client, admin_headers, po["id"])
    response = _send(client, admin_headers, po["id"])
    assert response.status_code == 422


# --- guard rails --------------------------------------------------------------


def test_cancel_requires_reason(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    response = client.patch(f"/api/purchase-orders/{po['id']}/status", json={"status": "cancelled"}, headers=admin_headers)
    assert response.status_code == 422


def test_cancel_allowed_from_issued(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _issue(client, admin_headers, po["id"])
    response = _cancel(client, admin_headers, po["id"])
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancel_reason"] == "Supplier out of stock"


def test_cannot_issue_a_cancelled_purchase_order(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _cancel(client, admin_headers, po["id"])
    response = _issue(client, admin_headers, po["id"])
    assert response.status_code == 400


# --- organisation isolation ---------------------------------------------------


def test_cross_organisation_purchase_order_404s(
    client, admin_headers, acme_supplier, warehouse_1, other_organisation, db_session
):
    other_po = PurchaseOrder(
        organisation_id=other_organisation.id,
        po_number="2650001",
        supplier_id=acme_supplier.id,
        warehouse_id=warehouse_1.id,
        status="draft",
        order_date=date(2026, 1, 1),
    )
    db_session.add(other_po)
    db_session.commit()

    response = client.get(f"/api/purchase-orders/{other_po.id}", headers=admin_headers)
    assert response.status_code == 404
