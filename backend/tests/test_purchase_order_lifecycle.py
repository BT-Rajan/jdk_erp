"""docs/modules/purchase_orders.md Revision 6: supplier follow-up history,
warehouse receiving without prices, automatic receipt reconciliation back
to the PO creator, payment reconciliation, and automatic closing only when
fully received, nothing open, and paid == final amount."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.roles import TEAM_MEMBER
from app.models.role_permission import RolePermission
from app.services import email_service

FUTURE = (date.today() + timedelta(days=30)).isoformat()
PRICE_KEYS = {"unit_price", "line_total", "total_amount", "final_amount", "paid_amount", "outstanding_amount", "payment_terms", "payments"}


def _login(client, username, password="Str0ng!Pass"):
    return {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': username, 'password': password}).json()['access_token']}"}


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login(client, "admin_person")


def _grant(db_session, organisation, module_key, action):
    db_session.add(RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key=module_key, action=action, scope="all"))
    db_session.commit()


@pytest.fixture()
def warehouse_headers(client, db_session, organisation, active_user):
    """A team member with only `purchase:receive` -- the warehouse."""
    _grant(db_session, organisation, "purchase", "receive")
    return _login(client, "ada")


def _sent_po(client, headers, supplier_id, warehouse_id, material_id, quantity="100", unit_price="10"):
    po = client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier_id, "warehouse_id": warehouse_id, "expected_delivery_date": FUTURE, "payment_terms": "Others: 30 days"},
        headers=headers,
    ).json()
    client.post(f"/api/purchase-orders/{po['id']}/lines", json={"raw_material_id": material_id, "quantity": quantity, "unit_price": unit_price}, headers=headers)
    client.post(f"/api/purchase-orders/{po['id']}/submit", headers=headers)
    client.post(f"/api/purchase-orders/{po['id']}/approve", headers=headers)
    body = client.post(f"/api/purchase-orders/{po['id']}/send", json={"email": False}, headers=headers).json()
    return body, body["lines"][0]["id"]


def _receive(client, headers, po_id, line_id, quantity, receipt_date=None, remarks=None):
    return client.post(
        f"/api/goods-receiving/{po_id}/receipts",
        json={
            "receipt_date": receipt_date or date.today().isoformat(),
            "supplier_delivery_reference": "DN-1",
            "lines": [{"purchase_order_line_id": line_id, "quantity": quantity, "remarks": remarks}],
        },
        headers=headers,
    )


def _po(client, headers, po_id):
    return client.get(f"/api/purchase-orders/{po_id}", headers=headers).json()


def _resolve(client, headers, po_body, resolution, note="Agreed with supplier"):
    rec = next(r for r in po_body["reconciliations"] if r["status"] == "open")
    return client.post(
        f"/api/purchase-orders/{po_body['id']}/reconciliations/{rec['id']}/resolve",
        json={"resolution": resolution, "note": note},
        headers=headers,
    )


def _pay(client, headers, po_id, amount, is_final=False):
    return client.post(
        f"/api/purchase-orders/{po_id}/payments",
        json={"payment_date": date.today().isoformat(), "amount": amount, "reference_number": "TX1", "is_final": is_final},
        headers=headers,
    )


def _keys(value) -> set:
    if isinstance(value, dict):
        return set(value) | set().union(*(_keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(_keys(v) for v in value)) if value else set()
    return set()


# --- warehouse ----------------------------------------------------------------------


def test_warehouse_sees_quantities_never_prices(
    client, admin_headers, warehouse_headers, acme_supplier, warehouse_1, cement_raw_material
):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)

    listing = client.get("/api/goods-receiving", headers=warehouse_headers)
    assert listing.status_code == 200
    detail = client.get(f"/api/goods-receiving/{po['id']}", headers=warehouse_headers)
    assert detail.status_code == 200
    assert detail.json()["lines"][0]["ordered_quantity"] == "100.0000"
    assert not (_keys(listing.json()) | _keys(detail.json())) & PRICE_KEYS

    # The commercial PO endpoints are closed to the warehouse.
    assert client.get(f"/api/purchase-orders/{po['id']}", headers=warehouse_headers).status_code == 403
    assert client.get("/api/purchase-orders", headers=warehouse_headers).status_code == 403
    assert client.patch(f"/api/purchase-orders/{po['id']}", json={"notes": "x"}, headers=warehouse_headers).status_code == 403
    legacy = client.post(
        f"/api/purchase-orders/{po['id']}/receipts",
        json={"receipt_date": date.today().isoformat(), "lines": [{"purchase_order_line_id": line_id, "quantity": "1"}]},
        headers=warehouse_headers,
    )
    assert legacy.status_code == 403


def test_full_receipt_matches_and_awaits_payment(client, admin_headers, warehouse_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    response = _receive(client, warehouse_headers, po["id"], line_id, "100", remarks="Bags intact")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "received"
    assert body["receipts"][0]["lines"][0]["remarks"] == "Bags intact"
    assert body["receipts"][0]["received_by_name"] == "Ada Lovelace"
    assert not _keys(body) & PRICE_KEYS
    assert _po(client, admin_headers, po["id"])["reconciliations"] == []


def test_late_delivery_is_shown_not_blocking(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    from app.models.purchase_order import PurchaseOrder

    row = db_session.query(PurchaseOrder).get(po["id"])
    row.expected_delivery_date = date.today() - timedelta(days=2)
    db_session.commit()
    body = _receive(client, admin_headers, po["id"], line_id, "100").json()
    assert body["status"] == "received"
    assert body["receipts"][0]["days_late"] == 2


def test_warehouse_cannot_receive_before_sent_or_in_future(client, admin_headers, warehouse_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert _receive(client, warehouse_headers, po["id"], line_id, "1", receipt_date=tomorrow).status_code == 422
    assert _receive(client, warehouse_headers, po["id"], line_id, "101").status_code == 422  # more than ordered

    draft = client.post(
        "/api/purchase-orders",
        json={"supplier_id": acme_supplier.id, "warehouse_id": warehouse_1.id, "expected_delivery_date": FUTURE, "payment_terms": "Advance"},
        headers=admin_headers,
    ).json()
    assert client.get(f"/api/goods-receiving/{draft['id']}", headers=warehouse_headers).status_code == 404


# --- receipt reconciliation --------------------------------------------------------


def test_short_receipt_goes_to_creator_keep_pending(client, admin_headers, warehouse_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    body = _receive(client, warehouse_headers, po["id"], line_id, "90").json()
    assert body["status"] == "reconciliation_required"
    assert body["can_receive"] is False

    full = _po(client, admin_headers, po["id"])
    rec = full["reconciliations"][0]
    assert (rec["kind"], rec["status"]) == ("receipt", "open")
    assert "ordered 100, received 90" in rec["discrepancy"]

    resolved = _resolve(client, admin_headers, full, "keep_pending", "Supplier sends 10 more on Friday")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "partially_received"
    assert resolved.json()["reconciliations"][0]["resolution_note"] == "Supplier sends 10 more on Friday"

    assert _receive(client, warehouse_headers, po["id"], line_id, "10").json()["status"] == "received"


def test_cancel_remaining_reduces_the_final_amount(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)  # 100 x 10
    _receive(client, admin_headers, po["id"], line_id, "90")
    body = _resolve(client, admin_headers, _po(client, admin_headers, po["id"]), "cancel_remaining").json()
    assert body["status"] == "received"
    assert body["lines"][0]["cancelled_quantity"] == "10.0000"
    assert body["final_amount"] == "900.0000"
    # Paying the reduced amount closes it.
    assert _pay(client, admin_headers, po["id"], "900").json()["status"] == "closed"


def test_accept_received_quantity_leaves_the_amount_owed_unchanged(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    """Outcome 1 (Accept Received Quantity) vs outcome 3 (Cancel Balance):
    both close out the line's outstanding balance the same mechanical way
    (cancelled_quantity absorbs the shortfall, since the original ordered
    quantity is never rewritten), but only Cancel Balance reduces what's
    owed. Accept Received Quantity holds final_amount unchanged via
    amount_adjustment -- the shortage is accepted operationally, not
    financially."""
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)  # 100 x 10
    _receive(client, admin_headers, po["id"], line_id, "90")
    resolved = _resolve(
        client, admin_headers, _po(client, admin_headers, po["id"]), "accept_received_quantity", "Supplier will not ship the rest; keep the agreed total"
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["status"] == "received"
    assert body["lines"][0]["cancelled_quantity"] == "10.0000"
    # The historical order itself is untouched.
    assert body["lines"][0]["quantity"] == "100.0000"
    assert body["lines"][0]["unit_price"] == "10.0000"
    # Unlike Cancel Balance, the full original amount is still owed.
    assert body["final_amount"] == "1000.0000"
    rec = body["reconciliations"][0]
    assert rec["resolution"] == "accept_received_quantity"
    assert rec["resolution_note"] == "Supplier will not ship the rest; keep the agreed total"
    assert rec["resolved_by_user_id"] is not None
    assert rec["resolved_at"] is not None

    # Paying only the reduced (900) amount does NOT close it -- the full
    # 1000 is still owed.
    assert _pay(client, admin_headers, po["id"], "900", is_final=True).json()["status"] == "payment_reconciliation"


def test_reconciliation_resolutions_do_not_rewrite_the_original_po(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    """Supplier, unit and the original ordered quantity/price are never
    rewritten by any of the three receipt resolutions."""
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    original_line = po["lines"][0]
    _receive(client, admin_headers, po["id"], line_id, "90")
    resolved = _resolve(
        client, admin_headers, _po(client, admin_headers, po["id"]), "keep_pending", "Awaiting the rest"
    ).json()
    line = resolved["lines"][0]
    assert (line["quantity"], line["unit_price"], line["unit_of_measure_id"]) == (
        original_line["quantity"], original_line["unit_price"], original_line["unit_of_measure_id"],
    )
    assert resolved["supplier_id"] == po["supplier_id"]
    assert resolved["status"] == "partially_received"
    assert resolved["lines"][0]["cancelled_quantity"] == "0.0000"


def test_only_the_creator_resolves(client, admin_headers, db_session, organisation, active_user, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    _receive(client, admin_headers, po["id"], line_id, "50")
    _grant(db_session, organisation, "purchase", "view")
    other = _login(client, "ada")
    assert _resolve(client, other, _po(client, admin_headers, po["id"]), "keep_pending").status_code == 403


def test_resolution_needs_a_note_and_a_matching_kind(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    _receive(client, admin_headers, po["id"], line_id, "50")
    full = _po(client, admin_headers, po["id"])
    assert _resolve(client, admin_headers, full, "keep_pending", note="  ").status_code == 422
    assert _resolve(client, admin_headers, full, "accept_paid_amount").status_code == 422


# --- payment and closing -----------------------------------------------------------


def test_exact_payment_after_receipt_closes_automatically(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    # Advance payment first: paid, but nothing received -> not closed.
    assert _pay(client, admin_headers, po["id"], "1000").json()["status"] == "sent"
    body = _receive(client, admin_headers, po["id"], line_id, "100").json()
    assert body["status"] == "closed"
    # Closed is final.
    payment_id = _po(client, admin_headers, po["id"])["payments"][0]["id"]
    cancel = client.post(f"/api/purchase-orders/{po['id']}/payments/{payment_id}/cancel", json={"reason": "x"}, headers=admin_headers)
    assert cancel.status_code == 400
    assert _pay(client, admin_headers, po["id"], "1").status_code == 400


def test_final_payment_that_differs_goes_to_creator(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    _receive(client, admin_headers, po["id"], line_id, "100")
    body = _pay(client, admin_headers, po["id"], "950", is_final=True).json()
    assert body["status"] == "payment_reconciliation"
    assert "difference -50" in body["reconciliations"][0]["discrepancy"]

    # Creator accepts the paid amount (e.g. agreed discount) -> closes.
    closed = _resolve(client, admin_headers, body, "accept_paid_amount", "Supplier gave 50 KWD discount").json()
    assert closed["status"] == "closed"
    assert closed["final_amount"] == "950.0000"
    assert closed["amount_adjustment"] == "-50.0000"


def test_overpayment_correct_payment_path(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line_id = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    _receive(client, admin_headers, po["id"], line_id, "100")
    body = _pay(client, admin_headers, po["id"], "1020").json()
    assert body["status"] == "payment_reconciliation"
    assert _resolve(client, admin_headers, body, "correct_payment", "Finance to fix the entry").json()["status"] == "received"

    # Finance corrects: cancel the wrong payment, record the right one.
    payment_id = body["payments"][0]["id"]
    client.post(f"/api/purchase-orders/{po['id']}/payments/{payment_id}/cancel", json={"reason": "Wrong amount"}, headers=admin_headers)
    assert _pay(client, admin_headers, po["id"], "1000", is_final=True).json()["status"] == "closed"


# --- follow-up -------------------------------------------------------------------------


def test_follow_up_email_and_supplier_reply_are_kept_on_the_po(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session, monkeypatch
):
    acme_supplier.email = "sales@acme.example"
    db_session.commit()
    po, _ = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    sent = {}
    monkeypatch.setattr(email_service, "send_email", lambda db, org, to, subject, body, data, name: sent.update(to=to, subject=subject, pdf=data))

    email = client.post(
        f"/api/purchase-orders/{po['id']}/follow-ups",
        json={"message": "Please confirm delivery date.", "attach_po_pdf": True},
        headers=admin_headers,
    )
    assert email.status_code == 201, email.text
    assert sent["to"] == "sales@acme.example"
    assert sent["pdf"].startswith(b"%PDF")

    reply = client.post(
        f"/api/purchase-orders/{po['id']}/follow-ups",
        json={"send_email": False, "message": "Supplier confirmed delivery for 30-09"},
        headers=admin_headers,
    ).json()
    history = [(c["kind"], c["status"]) for c in reply["communications"]]
    assert history == [("po_sent", "recorded"), ("follow_up", "sent"), ("note", "recorded")]
    assert reply["communications"][1]["subject"] == f"Follow-up: Purchase Order {po['po_number']}"
    assert reply["communications"][1]["sent_by_name"] is not None


def test_failed_follow_up_email_is_kept_with_its_status(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session):
    acme_supplier.email = "sales@acme.example"
    db_session.commit()
    po, _ = _sent_po(client, admin_headers, acme_supplier.id, warehouse_1.id, cement_raw_material.id)
    response = client.post(f"/api/purchase-orders/{po['id']}/follow-ups", json={"message": "Any update?"}, headers=admin_headers)
    assert response.status_code == 400  # no mailbox configured in tests
    entry = _po(client, admin_headers, po["id"])["communications"][-1]
    assert (entry["kind"], entry["status"]) == ("follow_up", "failed")
    assert entry["error"]
