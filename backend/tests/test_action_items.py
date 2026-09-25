"""Tests for the Action Required view (gap-fix): a read-only, aggregated
list of RFQs/POs already sitting in an existing actionable state --
awaiting supplier response, needing a decision, pending approval,
overdue, requiring payment, requiring reconciliation, or with an
outstanding balance after partial receipt. Every item must appear while
its state is actionable, disappear once resolved, and never appear once
cancelled/closed -- and clicking through must land on the real existing
record."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.purchase_order import PurchaseOrder

FUTURE = (date.today() + timedelta(days=30)).isoformat()


def _login(client, username, password="Str0ng!Pass"):
    return {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': username, 'password': password}).json()['access_token']}"}


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login(client, "admin_person")


def _items(client, headers):
    response = client.get("/api/action-items", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _by_type(items, item_type):
    return [i for i in items if i["type"] == item_type]


# --- RFQ ------------------------------------------------------------------------------------


def _issue_rfq_for(client, headers, supplier, material):
    body = client.post(
        "/api/rfqs",
        json={
            "required_delivery_date": FUTURE,
            "priority": "normal",
            "supplier_ids": [supplier.id],
            "lines": [{"raw_material_id": material.id, "unit_of_measure_id": material.unit_of_measure_id, "quantity": "10"}],
            "submit": True,
        },
        headers=headers,
    ).json()
    return body, body["invitations"][0]["id"]


def _capture_and_accept(client, headers, rfq, invitation_id, price="10"):
    upload = client.post(
        "/api/files", headers=headers, files={"upload": ("q.pdf", b"%PDF-1.4 fake", "application/pdf")}
    ).json()
    captured = client.post(
        f"/api/rfqs/{rfq['id']}/invitations/{invitation_id}/responses",
        json={"lines": [{"rfq_line_id": rfq["lines"][0]["id"], "unit_price": price}], "file_ids": []},
        headers=headers,
    ).json()
    response_id = captured["invitations"][0]["responses"][0]["id"]
    accepted = client.patch(
        f"/api/rfqs/{rfq['id']}/decision",
        json={"decision": "selected", "selected_response_id": response_id, "file_ids": [upload["id"]], "quantities_confirmed": True},
        headers=headers,
    )
    return accepted


def test_rfq_awaiting_response_appears_and_disappears_once_a_decision_is_made(
    client, admin_headers, acme_supplier, cement_raw_material
):
    rfq, invitation_id = _issue_rfq_for(client, admin_headers, acme_supplier, cement_raw_material)
    items = _items(client, admin_headers)
    awaiting = [i for i in _by_type(items, "rfq_awaiting_response") if i["id"] == rfq["id"]]
    assert len(awaiting) == 1
    assert awaiting[0]["reference"] == rfq["rfq_number"]
    assert awaiting[0]["entity"] == "rfq"

    # Clicking through must land on the real, existing RFQ record.
    fetched = client.get(f"/api/rfqs/{awaiting[0]['id']}", headers=admin_headers)
    assert fetched.status_code == 200
    assert fetched.json()["rfq_number"] == rfq["rfq_number"]

    # A captured response moves it to "needs decision", not "awaiting response".
    client.post(
        f"/api/rfqs/{rfq['id']}/invitations/{invitation_id}/responses",
        json={"lines": [{"rfq_line_id": rfq["lines"][0]["id"], "unit_price": "10"}], "file_ids": []},
        headers=admin_headers,
    )
    items = _items(client, admin_headers)
    assert not [i for i in _by_type(items, "rfq_awaiting_response") if i["id"] == rfq["id"]]
    needs_decision = [i for i in _by_type(items, "rfq_needs_decision") if i["id"] == rfq["id"]]
    assert len(needs_decision) == 1
    assert needs_decision[0]["detail"] == "1/1 supplier(s) responded"

    # Deciding (selecting) resolves it -- it disappears entirely.
    accepted = _capture_and_accept(client, admin_headers, rfq, invitation_id)
    assert accepted.status_code == 200, accepted.text
    items = _items(client, admin_headers)
    assert not [i for i in items if i["entity"] == "rfq" and i["id"] == rfq["id"]]


def test_cancelled_rfq_does_not_appear(client, admin_headers, acme_supplier, cement_raw_material):
    rfq, _ = _issue_rfq_for(client, admin_headers, acme_supplier, cement_raw_material)
    cancelled = client.patch(
        f"/api/rfqs/{rfq['id']}/status", json={"status": "cancelled", "cancel_reason": "No longer needed"}, headers=admin_headers
    )
    assert cancelled.status_code == 200, cancelled.text
    items = _items(client, admin_headers)
    assert not [i for i in items if i["entity"] == "rfq" and i["id"] == rfq["id"]]


# --- Purchase Order ---------------------------------------------------------------------------


def _create_po(client, headers, supplier_id, warehouse_id):
    return client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier_id, "warehouse_id": warehouse_id, "expected_delivery_date": FUTURE, "payment_terms": "Others: 30 days"},
        headers=headers,
    ).json()


def _add_line(client, headers, po_id, raw_material_id, quantity, unit_price):
    return client.post(
        f"/api/purchase-orders/{po_id}/lines",
        json={"raw_material_id": raw_material_id, "quantity": quantity, "unit_price": unit_price},
        headers=headers,
    )


def _submitted_po(client, headers, supplier_id, warehouse_id, material_id, quantity="100", unit_price="10"):
    po = _create_po(client, headers, supplier_id, warehouse_id)
    _add_line(client, headers, po["id"], material_id, quantity, unit_price)
    client.post(f"/api/purchase-orders/{po['id']}/submit", headers=headers)
    return client.get(f"/api/purchase-orders/{po['id']}", headers=headers).json()


def _sent_po(client, headers, supplier_id, warehouse_id, material_id, quantity="100", unit_price="10"):
    po = _submitted_po(client, headers, supplier_id, warehouse_id, material_id, quantity, unit_price)
    client.post(f"/api/purchase-orders/{po['id']}/approve", headers=headers)
    body = client.post(f"/api/purchase-orders/{po['id']}/send", json={"email": False}, headers=headers).json()
    return body, body["lines"][0]["id"]


def _receive(client, headers, po_id, line_id, quantity):
    return client.post(
        f"/api/goods-receiving/{po_id}/receipts",
        json={"receipt_date": date.today().isoformat(), "supplier_delivery_reference": "DN-1", "lines": [{"purchase_order_line_id": line_id, "quantity": quantity}]},
        headers=headers,
    )


def test_po_pending_approval_appears_and_disappears_once_approved(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po = _submitted_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    assert po["status"] == "pending_approval"
    items = _items(client, admin_headers)
    match = [i for i in _by_type(items, "po_pending_approval") if i["id"] == po["id"]]
    assert len(match) == 1
    assert match[0]["reference"] == po["po_number"]
    assert match[0]["supplier_name"] == "Acme Traders"

    fetched = client.get(f"/api/purchase-orders/{match[0]['id']}", headers=admin_headers)
    assert fetched.status_code == 200
    assert fetched.json()["po_number"] == po["po_number"]

    client.post(f"/api/purchase-orders/{po['id']}/approve", headers=admin_headers)
    items = _items(client, admin_headers)
    assert not [i for i in _by_type(items, "po_pending_approval") if i["id"] == po["id"]]


def test_po_overdue_appears_and_disappears_once_fully_received(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    row = db_session.query(PurchaseOrder).get(po["id"])
    row.expected_delivery_date = date.today() - timedelta(days=4)
    db_session.commit()

    items = _items(client, admin_headers)
    match = [i for i in _by_type(items, "po_overdue") if i["id"] == po["id"]]
    assert len(match) == 1
    assert match[0]["detail"] == "Overdue 4 day(s)"

    _receive(client, admin_headers, po["id"], line_id, "100")
    items = _items(client, admin_headers)
    assert not [i for i in _by_type(items, "po_overdue") if i["id"] == po["id"]]


def test_po_requires_payment_appears_and_disappears_once_paid(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po, _ = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)  # total = 1000
    items = _items(client, admin_headers)
    match = [i for i in _by_type(items, "po_requires_payment") if i["id"] == po["id"]]
    assert len(match) == 1
    assert "1000.0000" in match[0]["detail"]

    client.post(
        f"/api/purchase-orders/{po['id']}/payments",
        json={"payment_date": date.today().isoformat(), "amount": "1000", "reference_number": "TX1"},
        headers=admin_headers,
    )
    items = _items(client, admin_headers)
    assert not [i for i in _by_type(items, "po_requires_payment") if i["id"] == po["id"]]


def test_po_requires_reconciliation_appears_and_disappears_once_resolved(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    _receive(client, admin_headers, po["id"], line_id, "40")  # short receipt -> reconciliation_required
    items = _items(client, admin_headers)
    match = [i for i in _by_type(items, "po_requires_reconciliation") if i["id"] == po["id"]]
    assert len(match) == 1
    assert match[0]["detail"] and "short" in match[0]["detail"].lower()

    current = client.get(f"/api/purchase-orders/{po['id']}", headers=admin_headers).json()
    rec_id = next(r for r in current["reconciliations"] if r["status"] == "open")["id"]
    resolved = client.post(
        f"/api/purchase-orders/{po['id']}/reconciliations/{rec_id}/resolve",
        json={"resolution": "cancel_remaining", "note": "Supplier confirmed no more coming"},
        headers=admin_headers,
    )
    assert resolved.status_code == 200, resolved.text
    items = _items(client, admin_headers)
    assert not [i for i in _by_type(items, "po_requires_reconciliation") if i["id"] == po["id"]]


def test_po_partially_received_appears(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    _receive(client, admin_headers, po["id"], line_id, "40")
    current = client.get(f"/api/purchase-orders/{po['id']}", headers=admin_headers).json()
    rec_id = next(r for r in current["reconciliations"] if r["status"] == "open")["id"]
    # "keep_pending" resolves the discrepancy -- the PO settles into partially_received,
    # awaiting the rest, with no open reconciliation.
    client.post(
        f"/api/purchase-orders/{po['id']}/reconciliations/{rec_id}/resolve",
        json={"resolution": "keep_pending", "note": "Rest arriving next week"},
        headers=admin_headers,
    )
    refetched = client.get(f"/api/purchase-orders/{po['id']}", headers=admin_headers).json()
    assert refetched["status"] == "partially_received"

    items = _items(client, admin_headers)
    match = [i for i in _by_type(items, "po_partially_received") if i["id"] == po["id"]]
    assert len(match) == 1
    assert match[0]["detail"] == "1 line(s) short"
    assert not [i for i in _by_type(items, "po_requires_reconciliation") if i["id"] == po["id"]]


def test_cancelled_and_closed_pos_do_not_appear(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    # Cancelled, overdue -- must not appear despite the past delivery date.
    cancelled_po, _ = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    row = db_session.query(PurchaseOrder).get(cancelled_po["id"])
    row.expected_delivery_date = date.today() - timedelta(days=2)
    db_session.commit()
    client.patch(
        f"/api/purchase-orders/{cancelled_po['id']}/status",
        json={"status": "cancelled", "cancel_reason": "Supplier out of stock"},
        headers=admin_headers,
    )

    # Fully received and paid -- closes automatically, must not appear.
    closed_po, closed_line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    _receive(client, admin_headers, closed_po["id"], closed_line_id, "100")
    closed = client.post(
        f"/api/purchase-orders/{closed_po['id']}/payments",
        json={"payment_date": date.today().isoformat(), "amount": "1000", "reference_number": "TX1", "is_final": True},
        headers=admin_headers,
    ).json()
    assert closed["status"] == "closed"

    items = _items(client, admin_headers)
    ids = {i["id"] for i in items if i["entity"] == "purchase_order"}
    assert cancelled_po["id"] not in ids
    assert closed_po["id"] not in ids


def test_team_member_with_no_grants_sees_nothing(
    client, active_user, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    """No new permission is introduced -- a user with neither rfq:view
    nor purchase:view sees an empty list, exactly what the existing RFQ/
    PO list screens would already deny them."""
    _submitted_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    headers = _login(client, "ada")
    assert _items(client, headers) == []
