"""Sales documents: Quotation, Order Confirmation (Sales Order) and
Delivery Note PDFs, stored as FileRecords like the RFQ/PO PDFs and
downloaded through GET /api/files/{id} with the record's own access
rules. Rendered on the agreed events; every render is kept, the latest
is offered."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.customer import Customer
from app.models.file import FileRecord
from app.models.role_permission import RolePermission
from app.models.user import User
from app.services import (
    feasibility_record_service,
    finished_goods_inventory_service,
    quotation_readiness_service,
    sales_document_service,
    working_calendar_service,
)

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(client, db_session, organisation, widget_product, warehouse_1, monkeypatch):
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr("app.api.delivery_instructions.now_jdk", lambda: MONDAY_9AM_KUWAIT)
    for username, role in (("salesman_a", TEAM_MEMBER), ("salesman_b", TEAM_MEMBER), ("warehouse", "manager"), ("boss", ADMIN)):
        db_session.add(User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        ))
    db_session.add(RolePermission(organisation_id=organisation.id, role="manager", module_key="inventory", action="deliver", scope="all"))
    db_session.commit()
    salesman = db_session.query(User).filter(User.username == "salesman_a").one()
    customer = Customer(
        organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=salesman.id,
        phone="96511111111", address="Shuwaikh", payment_arrangement="after_delivery",
    )
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    db_session.add(customer)
    db_session.commit()
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=widget_product.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("500"), unit_of_measure_id=widget_product.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    db_session.commit()
    line = {"product_id": widget_product.id, "quantity": "10", "unit_of_measure_id": widget_product.unit_of_measure_id, "unit_price": "100"}
    return customer, line


def _pdfs(db_session, entity_type, entity_id):
    db_session.expire_all()
    return db_session.query(FileRecord).filter(FileRecord.entity_type == entity_type, FileRecord.entity_id == entity_id).count()


def _download(client, file_id, username):
    return client.get(f"/api/files/{file_id}", headers=_headers(client, username))


def test_quotation_pdf_on_every_save_and_scoped_download(client, db_session, setup):
    customer, line = setup
    a = _headers(client, "salesman_a")
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "lines": [line]}, headers=a).json()
    first = client.get(f"/api/quotations/{quotation['id']}", headers=a).json()["pdf_file"]
    assert first["original_filename"] == f"Quotation-{quotation['quotation_number']}.pdf"

    response = _download(client, first["id"], "salesman_a")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    # Out of the other salesman's customer scope: refused.
    assert _download(client, first["id"], "salesman_b").status_code == 403

    # An edit renders a new one; a no-change save does not.
    edited = client.patch(f"/api/quotations/{quotation['id']}", json={"requested_delivery_date": "2026-10-12"}, headers=a).json()
    assert edited["pdf_file"]["id"] != first["id"]
    assert _pdfs(db_session, sales_document_service.QUOTATION_PDF, quotation["id"]) == 2
    client.patch(f"/api/quotations/{quotation['id']}", json={"requested_delivery_date": "2026-10-12"}, headers=a)
    assert _pdfs(db_session, sales_document_service.QUOTATION_PDF, quotation["id"]) == 2


def test_order_confirmation_on_creation_and_admin_edit(client, db_session, setup):
    customer, line = setup
    a = _headers(client, "salesman_a")
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    order = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()
    assert order["pdf_file"]["original_filename"] == f"Order-Confirmation-{order['order_number']}.pdf"
    assert _download(client, order["pdf_file"]["id"], "salesman_a").content.startswith(b"%PDF")
    assert _download(client, order["pdf_file"]["id"], "salesman_b").status_code == 403

    edited = client.patch(
        f"/api/sales-orders/{order['id']}", json={"reason": "Customer asked", "requested_delivery_date": "2026-10-19"},
        headers=_headers(client, "boss"),
    ).json()
    assert edited["pdf_file"]["id"] != order["pdf_file"]["id"]
    assert _pdfs(db_session, sales_document_service.SALES_ORDER_PDF, order["id"]) == 2
    # The list does not carry it; the detail does.
    listed = client.get("/api/sales-orders", headers=a).json()["data"][0]
    assert listed["pdf_file"] is None
    assert client.get(f"/api/sales-orders/{order['id']}", headers=a).json()["pdf_file"]["id"] == edited["pdf_file"]["id"]


def test_delivery_note_follows_the_pending_shipment_and_is_final_at_fulfilment(client, db_session, setup, monkeypatch):
    customer, line = setup
    rendered = []
    real = sales_document_service.generate_sales_document_pdf
    monkeypatch.setattr(sales_document_service, "generate_sales_document_pdf", lambda data: rendered.append(data) or real(data))
    a = _headers(client, "salesman_a")
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
    client.post(f"/api/quotations/{quotation['id']}/accept", headers=a)
    order = client.post(f"/api/quotations/{quotation['id']}/convert", headers=a).json()

    wh = _headers(client, "warehouse")
    body = {"sales_order_id": order["id"], "lines": [{"sales_order_line_id": order["lines"][0]["id"], "quantity": "4"}]}
    instruction = client.post("/api/delivery-instructions", json=body, headers=wh).json()
    note = instruction["pdf_file"]
    assert note["original_filename"] == f"Delivery-Note-{instruction['delivery_number']}.pdf"
    assert _download(client, note["id"], "warehouse").content.startswith(b"%PDF")
    # Quantities only: no price column or totals on a Delivery Note.
    data = rendered[-1]
    assert data.title == "Delivery Note" and data.totals == []
    assert [c.label for c in data.columns] == ["#", "Product", "Quantity", "Unit", "Pallets"]
    assert data.rows[0][2:] == ["4", data.rows[0][3], "-"]
    # Without the delivery grant (the salesman), the note is refused.
    assert _download(client, note["id"], "salesman_a").status_code == 403

    line_url = f"/api/delivery-instructions/{instruction['id']}/lines/{instruction['lines'][0]['id']}"
    updated = client.patch(line_url, json={"pallet_count": 2}, headers=wh).json()
    assert updated["pdf_file"]["id"] != note["id"]
    fulfilled = client.post(f"/api/delivery-instructions/{instruction['id']}/fulfil", headers=wh).json()
    assert fulfilled["pdf_file"]["id"] == updated["pdf_file"]["id"]
    assert _pdfs(db_session, sales_document_service.DELIVERY_NOTE_PDF, instruction["id"]) == 2
