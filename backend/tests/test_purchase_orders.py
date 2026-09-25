"""Tests for docs/modules/purchase_orders.md: Draft -> Pending Approval ->
Approved (immutable revision + PDF) -> Sent -> Received, with required
header fields, per-line purchase unit, approval/sent/cancel stamps,
payment status, revisions, email sending, guard rails, organisation
isolation and permissions. Goods receipts and payments have their own
test files."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.roles import SUPER_ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.models.audit_event import (
    AuditEvent,
    PURCHASE_ORDER_APPROVED,
    PURCHASE_ORDER_SEND_FAILED,
    PURCHASE_ORDER_STATUS_CHANGED,
)
from app.models.file import FileRecord
from app.models.purchase_order import PurchaseOrder
from app.models.role_permission import RolePermission
from app.models.raw_material import RawMaterial
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.services import purchase_order_service

FUTURE = (date.today() + timedelta(days=30)).isoformat()


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_po(client, headers, supplier_id, warehouse_id, notes=None, **extra):
    body = {
        "supplier_id": supplier_id, "warehouse_id": warehouse_id, "expected_delivery_date": FUTURE,
        "payment_terms": "Others: 30 days", "notes": notes, **extra,
    }
    return client.post("/api/purchase-orders", json=body, headers=headers)


def _add_line(client, headers, po_id, raw_material_id, quantity, unit_price=None, **extra):
    payload = {"raw_material_id": raw_material_id, "quantity": quantity, **extra}
    if unit_price is not None:
        payload["unit_price"] = unit_price
    return client.post(f"/api/purchase-orders/{po_id}/lines", json=payload, headers=headers)


def _submit(client, headers, po_id):
    return client.post(f"/api/purchase-orders/{po_id}/submit", headers=headers)


def _approve(client, headers, po_id):
    return client.post(f"/api/purchase-orders/{po_id}/approve", headers=headers)


def _issue(client, headers, po_id):
    """Submit then approve."""
    submitted = _submit(client, headers, po_id)
    return submitted if submitted.status_code != 200 else _approve(client, headers, po_id)


def _reopen(client, headers, po_id):
    return client.patch(f"/api/purchase-orders/{po_id}/status", json={"status": "draft"}, headers=headers)


def _send(client, headers, po_id, email=True):
    return client.post(f"/api/purchase-orders/{po_id}/send", json={"email": email}, headers=headers)


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


def test_create_requires_expected_delivery_and_payment_terms(client, admin_headers, acme_supplier, warehouse_1):
    body = {"supplier_id": acme_supplier.id, "warehouse_id": warehouse_1.id}
    assert client.post("/api/purchase-orders", json=body, headers=admin_headers).status_code == 422
    assert client.post("/api/purchase-orders", json={**body, "expected_delivery_date": FUTURE}, headers=admin_headers).status_code == 422
    past = (date.today() - timedelta(days=1)).isoformat()
    assert _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id, expected_delivery_date=past).status_code == 422


def test_create_stamps_date_creator_and_currency(client, admin_headers, admin_user, acme_supplier, warehouse_1):
    body = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id, order_date="2020-01-01", delivery_instructions="Gate 2").json()
    assert body["order_date"] == date.today().isoformat()
    assert body["created_by_user_id"] == admin_user.id
    assert body["currency"] == "KWD"
    assert body["delivery_instructions"] == "Gate 2"
    assert body["payment_status"] == "unpaid"


def test_create_uses_the_warehouse_and_kwd(client, admin_headers, acme_supplier, warehouse_1, db_session):
    # A posted warehouse_id / currency is ignored: one warehouse, always KWD.
    body = {"supplier_id": acme_supplier.id, "expected_delivery_date": FUTURE, "payment_terms": "Others: 30 days", "currency": "USD", "warehouse_id": 999}
    created = client.post("/api/purchase-orders", json=body, headers=admin_headers)
    assert created.status_code == 201
    assert created.json()["warehouse_id"] == warehouse_1.id
    assert created.json()["currency"] == "KWD"

    warehouse_1.is_active = False
    db_session.commit()
    refused = client.post("/api/purchase-orders", json=body, headers=admin_headers)
    assert refused.status_code == 422
    assert "No active warehouse" in refused.json()["error"]["message"]


def test_add_line_requires_unit_price(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    assert _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10").status_code == 422


def test_line_unit_defaults_from_item_and_must_convert(
    client, admin_headers, db_session, organisation, electronics_category, mass_kilogram_unit, acme_supplier, warehouse_1, cement_raw_material
):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    line = _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", "5", remarks="Type 1").json()["lines"][0]
    assert line["unit_of_measure_id"] == cement_raw_material.unit_of_measure_id
    assert line["conversion_factor"] == "1.000000"
    assert line["remarks"] == "Type 1"

    tonne = UnitOfMeasure(organisation_id=organisation.id, name="Tonne", code="MT", dimension="mass", conversion_factor_to_base=1000, is_active=True)
    gravel = RawMaterial(organisation_id=organisation.id, code="RM9", name="Gravel", category_id=electronics_category.id, unit_of_measure_id=mass_kilogram_unit.id, is_active=True)
    db_session.add_all([tonne, gravel])
    db_session.commit()
    # Cement's plain KG has no dimension -- tonnes don't convert.
    assert _add_line(client, admin_headers, po["id"], cement_raw_material.id, "1", "5", unit_of_measure_id=tonne.id).status_code == 422
    ok = _add_line(client, admin_headers, po["id"], gravel.id, "2", "85", unit_of_measure_id=tonne.id)
    assert ok.status_code == 201
    gravel_line = next(l for l in ok.json()["lines"] if l["raw_material_id"] == gravel.id)
    assert (gravel_line["quantity"], gravel_line["conversion_factor"], gravel_line["line_total"]) == ("2.0000", "1000.000000", "170.0000")


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


# --- approval / revision lifecycle ------------------------------------------------


def test_cannot_submit_purchase_order_with_no_lines(client, admin_headers, acme_supplier, warehouse_1):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    assert _submit(client, admin_headers, po["id"]).status_code == 400


def test_cannot_approve_a_draft(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    assert _approve(client, admin_headers, po["id"]).status_code == 400


def test_approval_creates_revision_one_with_pdf_and_stamps(
    client, admin_headers, admin_user, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    submitted = _submit(client, admin_headers, po["id"])
    assert submitted.json()["status"] == "pending_approval"

    # Pending: not editable.
    assert client.patch(f"/api/purchase-orders/{po['id']}", json={"notes": "x"}, headers=admin_headers).status_code == 400

    response = _approve(client, admin_headers, po["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["approved_by_user_id"] == admin_user.id
    assert body["approved_at"] is not None
    assert body["revision_number"] == 1
    revision = body["revisions"][0]
    assert revision["total_amount"] == "50.0000"
    assert revision["lines"][0]["unit_of_measure_id"] == cement_raw_material.unit_of_measure_id
    assert revision["pdf_file"]["mime_type"] == "application/pdf"

    pdf_record = db_session.query(FileRecord).filter(FileRecord.id == revision["pdf_file"]["id"]).first()
    assert pdf_record.entity_type == "purchase_order_revision"
    assert db_session.query(AuditEvent).filter(AuditEvent.action == PURCHASE_ORDER_APPROVED, AuditEvent.entity_id == po["id"]).first()


def test_pending_po_can_be_sent_back_to_draft(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _submit(client, admin_headers, po["id"])
    back = _reopen(client, admin_headers, po["id"])
    assert back.json()["status"] == "draft"
    assert back.json()["revision_number"] == 0


def test_revision_needs_approval_again_and_preserves_revision_one(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    line = _add_line(client, admin_headers, po["id"], cement_raw_material.id, "100", unit_price="1.00").json()["lines"][0]
    _issue(client, admin_headers, po["id"])
    _send(client, admin_headers, po["id"], email=False)

    reopened = _reopen(client, admin_headers, po["id"])
    assert reopened.json()["status"] == "draft"
    client.patch(f"/api/purchase-orders/{po['id']}/lines/{line['id']}", json={"unit_price": "0.95"}, headers=admin_headers)
    body = _issue(client, admin_headers, po["id"]).json()
    assert body["status"] == "approved"
    assert body["revision_number"] == 2
    assert body["po_number"] == po["po_number"]
    revision_1 = next(r for r in body["revisions"] if r["revision_number"] == 1)
    revision_2 = next(r for r in body["revisions"] if r["revision_number"] == 2)
    assert revision_1["lines"][0]["unit_price"] == "1.0000"
    assert revision_2["lines"][0]["unit_price"] == "0.9500"


def test_cannot_reopen_a_draft_purchase_order(client, admin_headers, acme_supplier, warehouse_1):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    assert _reopen(client, admin_headers, po["id"]).status_code == 400


def test_mark_sent_without_email(client, admin_headers, admin_user, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _issue(client, admin_headers, po["id"])
    sent = _send(client, admin_headers, po["id"], email=False)
    assert sent.status_code == 200
    assert sent.json()["status"] == "sent"
    assert sent.json()["sent_by_user_id"] == admin_user.id
    assert _send(client, admin_headers, po["id"], email=False).status_code == 400


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
    assert po_row.status == "approved"


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


def test_cancel_allowed_from_approved_and_stamped(client, admin_headers, admin_user, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _issue(client, admin_headers, po["id"])
    response = _cancel(client, admin_headers, po["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancel_reason"] == "Supplier out of stock"
    assert body["cancelled_by_user_id"] == admin_user.id
    assert body["cancelled_at"] is not None


def test_cannot_issue_a_cancelled_purchase_order(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _cancel(client, admin_headers, po["id"])
    response = _issue(client, admin_headers, po["id"])
    assert response.status_code == 400


# --- gap fix: cancellation authority -- admin/super_admin only, never purchase:issue --------


def test_super_admin_can_cancel(client, db_session, organisation, acme_supplier, warehouse_1, cement_raw_material):
    db_session.add(
        User(
            organisation_id=organisation.id,
            role=SUPER_ADMIN,
            full_name="Super Admin",
            email="super_admin@example.com",
            username="super_admin_person",
            password_hash=hash_password("Str0ng!Pass"),
            is_active=True,
        )
    )
    db_session.commit()
    headers = _login_headers(client, "super_admin_person")

    po = _create_po(client, headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _issue(client, headers, po["id"])
    response = _cancel(client, headers, po["id"])
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def test_team_member_with_purchase_issue_cannot_cancel(
    client, active_user, organisation, db_session, acme_supplier, warehouse_1, cement_raw_material, admin_headers
):
    """purchase:issue is no longer cancellation authority -- only
    admin/super_admin may cancel (gap-fix: PO cancellation authority).
    The same grant still covers what it always did (sending a pending/
    approved/sent PO back to draft) -- nothing else about it changed."""
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase", action="view", scope="all")
    )
    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase", action="issue", scope="all")
    )
    db_session.commit()
    headers = _login_headers(client)

    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _issue(client, admin_headers, po["id"])

    denied = _cancel(client, headers, po["id"])
    assert denied.status_code == 403
    refetched = client.get(f"/api/purchase-orders/{po['id']}", headers=admin_headers).json()
    assert refetched["status"] != "cancelled"

    # The rest of what purchase:issue grants is unaffected.
    reopened = _reopen(client, headers, po["id"])
    assert reopened.status_code == 200
    assert reopened.json()["status"] == "draft"


def test_admin_cancellation_still_records_reason_and_audit_trail(
    client, admin_headers, admin_user, organisation, db_session, acme_supplier, warehouse_1, cement_raw_material
):
    po = _create_po(client, admin_headers, acme_supplier.id, warehouse_1.id).json()
    _add_line(client, admin_headers, po["id"], cement_raw_material.id, "10", unit_price="5")
    _issue(client, admin_headers, po["id"])
    response = _cancel(client, admin_headers, po["id"], reason="Supplier confirmed they cannot fulfil.")
    assert response.status_code == 200
    body = response.json()
    assert body["cancel_reason"] == "Supplier confirmed they cannot fulfil."
    assert body["cancelled_by_user_id"] == admin_user.id

    events = (
        db_session.query(AuditEvent)
        .filter(
            AuditEvent.action == PURCHASE_ORDER_STATUS_CHANGED,
            AuditEvent.entity_id == po["id"],
            AuditEvent.organisation_id == organisation.id,
        )
        .all()
    )
    assert len(events) == 1
    assert "cancelled" in events[0].details
    assert events[0].actor_user_id == admin_user.id


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
