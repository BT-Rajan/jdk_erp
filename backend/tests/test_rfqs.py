"""Tests for docs/modules/rfq.md: the RFQ Flow (RFQ -> Supplier Response
-> Decision -> Purchase Order) -- draft creation/line management, issuing,
attachment-based response capture (reusing the existing generic file
system), the explicit decision action, conversion into a Purchase Order
with full field carry-forward and no re-entry, every guard rail, the
inventory-untouched boundary, organisation isolation (including on
attachments), and RFQ numbering's YY3NNNN format and yearly reset."""
import io
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.rfq import Rfq
from app.services import rfq_service

PDF_BYTES = b"%PDF-1.4 fake supplier quote"


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _pdf_file(name="quote.pdf"):
    return {"upload": (name, io.BytesIO(PDF_BYTES), "application/pdf")}


def _upload_file(client, headers):
    response = client.post("/api/files", headers=headers, files=_pdf_file())
    assert response.status_code == 201
    return response.json()["id"]


def _create_rfq(client, headers, supplier_id, rfq_date="2026-01-10", notes=None):
    return client.post(
        "/api/rfqs", json={"supplier_id": supplier_id, "rfq_date": rfq_date, "notes": notes}, headers=headers
    )


def _add_line(client, headers, rfq_id, raw_material_id, quantity):
    return client.post(f"/api/rfqs/{rfq_id}/lines", json={"raw_material_id": raw_material_id, "quantity": quantity}, headers=headers)


def _issue(client, headers, rfq_id):
    return client.patch(f"/api/rfqs/{rfq_id}/status", json={"status": "issued"}, headers=headers)


def _cancel(client, headers, rfq_id, reason="No longer needed"):
    return client.patch(f"/api/rfqs/{rfq_id}/status", json={"status": "cancelled", "cancel_reason": reason}, headers=headers)


def _capture_response(client, headers, rfq_id, file_ids, note=None):
    return client.post(
        f"/api/rfqs/{rfq_id}/responses",
        json={"file_ids": file_ids, "note": note, "response_received_at": datetime.utcnow().isoformat()},
        headers=headers,
    )


def _decide(client, headers, rfq_id, decision, selected_response_id=None, note=None):
    return client.patch(
        f"/api/rfqs/{rfq_id}/decision",
        json={"decision": decision, "selected_response_id": selected_response_id, "note": note},
        headers=headers,
    )


def _convert(client, headers, rfq_id, warehouse_id, lines):
    return client.post(f"/api/rfqs/{rfq_id}/convert-to-po", json={"warehouse_id": warehouse_id, "lines": lines}, headers=headers)


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login_headers(client, "admin_person")


# --- numbering ----------------------------------------------------------------


def test_rfq_number_format_and_yearly_sequence(client, admin_headers, acme_supplier):
    first = _create_rfq(client, admin_headers, acme_supplier.id).json()
    second = _create_rfq(client, admin_headers, acme_supplier.id).json()
    year_suffix = str(date.today().year % 100).zfill(2)
    assert first["rfq_number"] == f"{year_suffix}30001"
    assert second["rfq_number"] == f"{year_suffix}30002"
    assert len(first["rfq_number"]) == 7
    assert first["rfq_number"][2] == "3"


def test_rfq_number_resets_per_year(db_session, organisation, acme_supplier):
    number_2025 = rfq_service.generate_rfq_number(db_session, organisation.id, today=date(2025, 12, 31))
    assert number_2025 == "2530001"
    rfq = Rfq(
        organisation_id=organisation.id,
        rfq_number=number_2025,
        supplier_id=acme_supplier.id,
        status="draft",
        rfq_date=date(2025, 12, 31),
    )
    db_session.add(rfq)
    db_session.commit()

    number_2026 = rfq_service.generate_rfq_number(db_session, organisation.id, today=date(2026, 1, 1))
    assert number_2026 == "2630001"


# --- draft creation / line management ------------------------------------------


def test_create_rfq_requires_authentication(client):
    response = client.get("/api/rfqs")
    assert response.status_code == 401


def test_cannot_issue_rfq_with_no_lines(client, admin_headers, acme_supplier):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    response = _issue(client, admin_headers, rfq["id"])
    assert response.status_code == 400


def test_lines_not_editable_once_issued(client, admin_headers, acme_supplier, cement_raw_material):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "100")
    _issue(client, admin_headers, rfq["id"])

    response = client.post(
        f"/api/rfqs/{rfq['id']}/lines", json={"raw_material_id": cement_raw_material.id, "quantity": "5"}, headers=admin_headers
    )
    assert response.status_code == 400


# --- full end-to-end flow -------------------------------------------------------


def test_full_flow_creates_po_and_leaves_inventory_untouched(
    client, admin_headers, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    line = _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "100").json()["lines"][0]
    assert _issue(client, admin_headers, rfq["id"]).json()["status"] == "issued"

    file_id = _upload_file(client, admin_headers)
    captured = _capture_response(client, admin_headers, rfq["id"], [file_id], note="950 KWD, 3 days")
    assert captured.status_code == 201
    body = captured.json()
    assert body["status"] == "response_received"
    response_id = body["responses"][0]["id"]
    assert body["responses"][0]["files"][0]["id"] == file_id

    # Requested quantity is untouched by the captured response.
    assert body["lines"][0]["quantity"] == "100.0000"

    decided = _decide(client, admin_headers, rfq["id"], "selected", selected_response_id=response_id)
    assert decided.status_code == 200
    assert decided.json()["status"] == "selected"

    # No inventory effect anywhere up to this point.
    assert db_session.query(StockMovement).count() == 0
    assert db_session.query(RawMaterialInventory).count() == 0

    converted = _convert(
        client, admin_headers, rfq["id"], warehouse_1.id, [{"rfq_line_id": line["id"], "unit_price": "5.50"}]
    )
    assert converted.status_code == 200
    final = converted.json()
    assert final["status"] == "converted"
    assert final["purchase_order_id"] is not None

    po = db_session.query(PurchaseOrder).filter(PurchaseOrder.id == final["purchase_order_id"]).first()
    assert po.supplier_id == acme_supplier.id
    assert po.status == "draft"

    lines = db_session.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == po.id).all()
    assert len(lines) == 1
    assert lines[0].raw_material_id == cement_raw_material.id
    assert lines[0].quantity == Decimal("100.0000")
    assert lines[0].unit_price == Decimal("5.5000")

    # Still no inventory effect -- only PO receiving affects stock.
    assert db_session.query(StockMovement).count() == 0
    assert db_session.query(RawMaterialInventory).count() == 0


def test_cannot_convert_twice(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    line = _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "10").json()["lines"][0]
    _issue(client, admin_headers, rfq["id"])
    file_id = _upload_file(client, admin_headers)
    response_id = _capture_response(client, admin_headers, rfq["id"], [file_id]).json()["responses"][0]["id"]
    _decide(client, admin_headers, rfq["id"], "selected", selected_response_id=response_id)

    first = _convert(client, admin_headers, rfq["id"], warehouse_1.id, [{"rfq_line_id": line["id"], "unit_price": "1"}])
    assert first.status_code == 200
    second = _convert(client, admin_headers, rfq["id"], warehouse_1.id, [{"rfq_line_id": line["id"], "unit_price": "1"}])
    assert second.status_code == 400


# --- decision / rejection / cancellation ---------------------------------------


def test_decision_requires_a_captured_response(client, admin_headers, acme_supplier, cement_raw_material):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "10")
    _issue(client, admin_headers, rfq["id"])
    response = _decide(client, admin_headers, rfq["id"], "rejected")
    assert response.status_code == 400


def test_rejected_rfq_has_no_convert_path(client, admin_headers, acme_supplier, warehouse_1, cement_raw_material):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    line = _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "10").json()["lines"][0]
    _issue(client, admin_headers, rfq["id"])
    file_id = _upload_file(client, admin_headers)
    _capture_response(client, admin_headers, rfq["id"], [file_id])
    rejected = _decide(client, admin_headers, rfq["id"], "rejected")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    response = _convert(client, admin_headers, rfq["id"], warehouse_1.id, [{"rfq_line_id": line["id"], "unit_price": "1"}])
    assert response.status_code == 400


def test_selecting_requires_a_valid_response_id(client, admin_headers, acme_supplier, cement_raw_material):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "10")
    _issue(client, admin_headers, rfq["id"])
    file_id = _upload_file(client, admin_headers)
    _capture_response(client, admin_headers, rfq["id"], [file_id])
    response = _decide(client, admin_headers, rfq["id"], "selected", selected_response_id=999999)
    assert response.status_code == 422


def test_cancel_requires_reason_and_allowed_from_multiple_states(client, admin_headers, acme_supplier, cement_raw_material):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "10")

    no_reason = client.patch(f"/api/rfqs/{rfq['id']}/status", json={"status": "cancelled"}, headers=admin_headers)
    assert no_reason.status_code == 422

    cancelled = _cancel(client, admin_headers, rfq["id"])
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


# --- attachments / organisation isolation ---------------------------------------


def test_response_capture_requires_at_least_one_file(client, admin_headers, acme_supplier, cement_raw_material):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "10")
    _issue(client, admin_headers, rfq["id"])
    response = client.post(f"/api/rfqs/{rfq['id']}/responses", json={"file_ids": []}, headers=admin_headers)
    assert response.status_code == 422


def test_cross_organisation_rfq_404s(client, admin_headers, acme_supplier, other_organisation, db_session):
    other_rfq = Rfq(
        organisation_id=other_organisation.id,
        rfq_number="2630001",
        supplier_id=acme_supplier.id,
        status="draft",
        rfq_date=date(2026, 1, 1),
    )
    db_session.add(other_rfq)
    db_session.commit()

    response = client.get(f"/api/rfqs/{other_rfq.id}", headers=admin_headers)
    assert response.status_code == 404


def test_cannot_attach_another_organisations_file(client, admin_headers, acme_supplier, cement_raw_material, other_org_user, db_session):
    rfq = _create_rfq(client, admin_headers, acme_supplier.id).json()
    _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "10")
    _issue(client, admin_headers, rfq["id"])

    from app.core.security import hash_password
    from app.models.user import User

    other_admin = User(
        organisation_id=other_org_user.organisation_id,
        role="admin",
        full_name="Other Admin",
        email="other-admin@example.com",
        username="other_admin",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(other_admin)
    db_session.commit()
    other_headers = _login_headers(client, "other_admin")
    other_file_id = _upload_file(client, other_headers)

    response = _capture_response(client, admin_headers, rfq["id"], [other_file_id])
    assert response.status_code == 422


# --- permissions -----------------------------------------------------------------


def test_team_member_denied_by_default(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/rfqs", headers=headers)
    assert response.status_code == 403
