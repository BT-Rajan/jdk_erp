"""Procurement duplicate protection: a repeated submission (double click,
retry after a timeout, second tab) of a goods receipt or a payment never
posts stock or money twice. The client sends one `client_reference` per
submission; a repeat returns the recorded receipt/payment (200) and posts
nothing. Separate submissions stay separate records."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.purchase_order import PurchaseOrderPayment, PurchaseOrderReceipt

FUTURE = (date.today() + timedelta(days=30)).isoformat()
TODAY = date.today().isoformat()


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def admin_headers(client, admin_user):
    return _headers(client, "admin_person")


def _sent_po(client, headers, supplier, warehouse, material, quantity="100", unit_price="10"):
    po = client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier.id, "warehouse_id": warehouse.id, "expected_delivery_date": FUTURE, "payment_terms": "Others: 30 days"},
        headers=headers,
    ).json()
    line = client.post(
        f"/api/purchase-orders/{po['id']}/lines",
        json={"raw_material_id": material.id, "quantity": quantity, "unit_price": unit_price},
        headers=headers,
    ).json()["lines"][0]
    client.post(f"/api/purchase-orders/{po['id']}/submit", headers=headers)
    client.post(f"/api/purchase-orders/{po['id']}/approve", headers=headers)
    client.post(f"/api/purchase-orders/{po['id']}/send", json={"email": False}, headers=headers)
    return po, line


def _stock(db_session, material):
    db_session.expire_all()
    on_hand = db_session.query(RawMaterialInventory.quantity_on_hand).filter(RawMaterialInventory.raw_material_id == material.id).scalar()
    return on_hand, db_session.query(StockMovement).count()


def _warehouse_receipt(client, headers, po, line, quantity, reference=None):
    body = {"receipt_date": TODAY, "lines": [{"purchase_order_line_id": line["id"], "quantity": quantity}]}
    if reference is not None:
        body["client_reference"] = reference
    return client.post(f"/api/goods-receiving/{po['id']}/receipts", json=body, headers=headers)


def _payment(client, headers, po, amount, reference=None):
    body = {"payment_date": TODAY, "amount": amount, "payment_method": "Bank Transfer"}
    if reference is not None:
        body["client_reference"] = reference
    return client.post(f"/api/purchase-orders/{po['id']}/payments", json=body, headers=headers)


def test_a_repeated_warehouse_receipt_posts_stock_once(client, db_session, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line = _sent_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    # 50 of 100: well within the ordered quantity, so only the reference stops a double post.
    first = _warehouse_receipt(client, admin_headers, po, line, "50", reference="rcv-1")
    assert first.status_code == 201, first.json()
    after_first = _stock(db_session, cement_raw_material)
    assert after_first[0] == Decimal("50")
    for _ in range(2):
        repeat = _warehouse_receipt(client, admin_headers, po, line, "50", reference="rcv-1")
        assert repeat.status_code == 200
    assert _stock(db_session, cement_raw_material) == after_first
    assert db_session.query(PurchaseOrderReceipt).count() == 1
    # A separate delivery is a separate receipt (after the creator keeps the
    # short balance pending -- the existing reconciliation step).
    body = client.get(f"/api/purchase-orders/{po['id']}", headers=admin_headers).json()
    rec = next(r for r in body["reconciliations"] if r["status"] == "open")
    client.post(
        f"/api/purchase-orders/{po['id']}/reconciliations/{rec['id']}/resolve",
        json={"resolution": "keep_pending", "note": "Balance to follow"},
        headers=admin_headers,
    )
    assert _warehouse_receipt(client, admin_headers, po, line, "30", reference="rcv-2").status_code == 201
    assert _stock(db_session, cement_raw_material)[0] == Decimal("80")
    assert db_session.query(PurchaseOrderReceipt).count() == 2


def test_a_repeated_draft_receipt_is_created_once(client, db_session, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, line = _sent_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    body = {"receipt_date": TODAY, "lines": [{"purchase_order_line_id": line["id"], "quantity": "40"}], "client_reference": "draft-1"}
    assert client.post(f"/api/purchase-orders/{po['id']}/receipts", json=body, headers=admin_headers).status_code == 201
    assert client.post(f"/api/purchase-orders/{po['id']}/receipts", json=body, headers=admin_headers).status_code == 200
    assert db_session.query(PurchaseOrderReceipt).count() == 1


def test_a_repeated_payment_is_recorded_once(client, db_session, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, _ = _sent_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    first = _payment(client, admin_headers, po, "300", reference="pay-1")
    assert first.status_code == 201, first.json()
    for _ in range(2):
        assert _payment(client, admin_headers, po, "300", reference="pay-1").status_code == 200
    payments = db_session.query(PurchaseOrderPayment).all()
    assert [p.amount for p in payments] == [Decimal("300")]
    assert Decimal(client.get(f"/api/purchase-orders/{po['id']}", headers=admin_headers).json()["paid_amount"]) == 300
    # The same reference for a different amount is refused, not merged or doubled.
    clash = _payment(client, admin_headers, po, "250", reference="pay-1")
    assert clash.status_code == 409 and "different payment" in clash.json()["error"]["message"]
    # A separate payment is a separate record.
    assert _payment(client, admin_headers, po, "200", reference="pay-2").status_code == 201
    assert db_session.query(PurchaseOrderPayment).count() == 2


def test_a_reference_cannot_be_reused_on_another_purchase_order(client, db_session, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po_a, line_a = _sent_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    po_b, line_b = _sent_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    assert _payment(client, admin_headers, po_a, "100", reference="same").status_code == 201
    assert _payment(client, admin_headers, po_b, "100", reference="same").status_code == 409
    assert _warehouse_receipt(client, admin_headers, po_a, line_a, "10", reference="same-r").status_code == 201
    assert _warehouse_receipt(client, admin_headers, po_b, line_b, "10", reference="same-r").status_code == 409
    assert db_session.query(PurchaseOrderPayment).count() == 1 and db_session.query(PurchaseOrderReceipt).count() == 1


def test_requests_without_a_reference_behave_as_before(client, db_session, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    po, _ = _sent_po(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material)
    assert _payment(client, admin_headers, po, "100").status_code == 201
    assert _payment(client, admin_headers, po, "100").status_code == 201
    assert db_session.query(PurchaseOrderPayment).count() == 2
