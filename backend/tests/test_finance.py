"""Tests for docs/modules/purchase_orders.md Revision 8: fixed payment
terms, and every approved PO going to Finance, who see it read-only and
record payments with only the purchase_payment grant."""
from datetime import date, timedelta

import pytest

from app.core.roles import TEAM_MEMBER
from app.models.role_permission import RolePermission


FUTURE = (date.today() + timedelta(days=30)).isoformat()


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_po(client, headers, supplier_id, payment_terms="Advance"):
    return client.post(
        "/api/purchase-orders",
        json={"supplier_id": supplier_id, "expected_delivery_date": FUTURE, "payment_terms": payment_terms},
        headers=headers,
    )


def _approved_po(client, headers, supplier_id, raw_material_id, payment_terms="Advance"):
    po = _create_po(client, headers, supplier_id, payment_terms).json()
    client.post(
        f"/api/purchase-orders/{po['id']}/lines",
        json={"raw_material_id": raw_material_id, "quantity": "10", "unit_price": "100"},
        headers=headers,
    )
    client.post(f"/api/purchase-orders/{po['id']}/submit", headers=headers)
    return client.post(f"/api/purchase-orders/{po['id']}/approve", headers=headers).json()


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login_headers(client, "admin_person")


@pytest.mark.parametrize(
    ("given", "stored"),
    [("Advance", "Advance"), ("prepaid", "Prepaid"), ("On Delivery", "On Delivery"), ("Others: 50% advance, 50% on delivery", "Others: 50% advance, 50% on delivery")],
)
def test_payment_terms_are_one_of_the_fixed_choices(client, admin_headers, acme_supplier, warehouse_1, given, stored):
    created = _create_po(client, admin_headers, acme_supplier.id, given)
    assert created.status_code == 201
    assert created.json()["payment_terms"] == stored


@pytest.mark.parametrize("given", ["30 days", "Others", "Others: ", ""])
def test_other_payment_terms_are_refused(client, admin_headers, acme_supplier, warehouse_1, given):
    assert _create_po(client, admin_headers, acme_supplier.id, given).status_code == 422


def test_every_approved_po_goes_to_finance_until_paid(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material
):
    draft = _create_po(client, admin_headers, acme_supplier.id).json()
    advance = _approved_po(client, admin_headers, acme_supplier.id, cement_raw_material.id, "Advance")
    prepaid = _approved_po(client, admin_headers, acme_supplier.id, cement_raw_material.id, "Prepaid")
    on_delivery = _approved_po(client, admin_headers, acme_supplier.id, cement_raw_material.id, "On Delivery")

    listed = client.get("/api/finance/purchase-orders", headers=admin_headers).json()
    assert [po["id"] for po in listed["data"]] == [advance["id"], prepaid["id"], on_delivery["id"]]
    assert draft["id"] not in [po["id"] for po in listed["data"]]

    detail = client.get(f"/api/finance/purchase-orders/{prepaid['id']}", headers=admin_headers).json()
    assert detail["payment_terms"] == "Prepaid"
    assert detail["outstanding_amount"] == "1000.0000"
    assert detail["lines"][0]["unit_price"] == "100.0000"

    paid = client.post(
        f"/api/purchase-orders/{prepaid['id']}/payments",
        json={"payment_date": date.today().isoformat(), "amount": "1000", "payment_method": "Bank Transfer", "notes": "Paid before PO"},
        headers=admin_headers,
    )
    assert paid.status_code == 201
    listed = client.get("/api/finance/purchase-orders", headers=admin_headers).json()
    assert prepaid["id"] not in [po["id"] for po in listed["data"]]
    detail = client.get(f"/api/finance/purchase-orders/{prepaid['id']}", headers=admin_headers).json()
    assert detail["payments"][0]["notes"] == "Paid before PO"
    assert detail["payment_status"] == "paid"


def test_finance_needs_only_the_payment_grant(
    client, admin_headers, active_user, organisation, db_session, acme_supplier, warehouse_1, cement_raw_material
):
    po = _approved_po(client, admin_headers, acme_supplier.id, cement_raw_material.id)
    headers = _login_headers(client)
    assert client.get("/api/finance/purchase-orders", headers=headers).status_code == 403
    assert client.get(f"/api/finance/purchase-orders/{po['id']}", headers=headers).status_code == 403

    db_session.add(
        RolePermission(organisation_id=organisation.id, role=TEAM_MEMBER, module_key="purchase_payment", action="create", scope="all")
    )
    db_session.commit()
    assert client.get("/api/finance/purchase-orders", headers=headers).status_code == 200
    assert client.get(f"/api/finance/purchase-orders/{po['id']}", headers=headers).status_code == 200
    # Still no access to Procurement's own PO record.
    assert client.get(f"/api/purchase-orders/{po['id']}", headers=headers).status_code == 403
