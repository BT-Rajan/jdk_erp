"""Tests for docs/modules/rfq.md (v2): RFQ -> Supplier Invitations ->
Structured Response(s) -> Comparison -> Decision -> Purchase Order.
Covers draft creation (department/requester/priority), line management
with remarks, supplier invitations, issuing guards, structured response
capture per invitation (with optional attachments), the comparison shape,
the explicit decision across suppliers, conversion into a Purchase Order
pre-filled from the selected response (with override), every guard rail,
the inventory-untouched boundary, organisation isolation, and RFQ
numbering's YY3NNNN format and yearly reset."""
import io
from datetime import date, datetime
from decimal import Decimal

import pytest

from app.core.security import hash_password
from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.raw_material import RawMaterial
from app.models.rfq import Rfq, RfqResponse, RfqResponseLine
from app.models.supplier import Supplier
from app.models.team import Team
from app.models.user import User
from app.services import rfq_service

PDF_BYTES = b"%PDF-1.4 fake supplier quote"


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _upload_file(client, headers):
    response = client.post(
        "/api/files", headers=headers, files={"upload": ("quote.pdf", io.BytesIO(PDF_BYTES), "application/pdf")}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_rfq(client, headers, rfq_date="2026-01-10", **extra):
    return client.post("/api/rfqs", json={"rfq_date": rfq_date, **extra}, headers=headers)


def _add_line(client, headers, rfq_id, raw_material_id, quantity, remarks=None):
    return client.post(
        f"/api/rfqs/{rfq_id}/lines",
        json={"raw_material_id": raw_material_id, "quantity": quantity, "remarks": remarks},
        headers=headers,
    )


def _invite(client, headers, rfq_id, supplier_id):
    return client.post(f"/api/rfqs/{rfq_id}/invitations", json={"supplier_id": supplier_id}, headers=headers)


def _issue(client, headers, rfq_id):
    return client.patch(f"/api/rfqs/{rfq_id}/status", json={"status": "issued"}, headers=headers)


def _cancel(client, headers, rfq_id, reason="No longer needed"):
    return client.patch(
        f"/api/rfqs/{rfq_id}/status", json={"status": "cancelled", "cancel_reason": reason}, headers=headers
    )


def _capture(client, headers, rfq_id, invitation_id, lines, file_ids=None, **extra):
    return client.post(
        f"/api/rfqs/{rfq_id}/invitations/{invitation_id}/responses",
        json={
            "lines": lines,
            "file_ids": file_ids or [],
            "response_received_at": datetime.utcnow().isoformat(),
            **extra,
        },
        headers=headers,
    )


def _decline(client, headers, rfq_id, invitation_id):
    return client.post(f"/api/rfqs/{rfq_id}/invitations/{invitation_id}/decline", headers=headers)


def _decide(client, headers, rfq_id, decision, selected_response_id=None, note=None):
    return client.patch(
        f"/api/rfqs/{rfq_id}/decision",
        json={"decision": decision, "selected_response_id": selected_response_id, "note": note},
        headers=headers,
    )


def _convert(client, headers, rfq_id, warehouse_id, lines=None):
    body = {"warehouse_id": warehouse_id}
    if lines is not None:
        body["lines"] = lines
    return client.post(f"/api/rfqs/{rfq_id}/convert-to-po", json=body, headers=headers)


def _invitation_for(rfq_body, supplier_id):
    return next(i for i in rfq_body["invitations"] if i["supplier_id"] == supplier_id)


@pytest.fixture()
def admin_headers(client, admin_user):
    return _login_headers(client, "admin_person")


@pytest.fixture()
def beta_supplier(db_session, organisation):
    supplier = Supplier(organisation_id=organisation.id, code="SUP0002", name="Beta Supplies", is_active=True)
    db_session.add(supplier)
    db_session.commit()
    db_session.refresh(supplier)
    return supplier


@pytest.fixture()
def sand_raw_material(db_session, organisation, electronics_category, kilogram_unit):
    material = RawMaterial(
        organisation_id=organisation.id,
        code="RM002",
        name="Sand",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        is_active=True,
    )
    db_session.add(material)
    db_session.commit()
    db_session.refresh(material)
    return material


@pytest.fixture()
def other_admin_headers(client, db_session, other_org_user):
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
    return _login_headers(client, "other_admin")


@pytest.fixture()
def issued_two_supplier_rfq(client, admin_headers, acme_supplier, beta_supplier, cement_raw_material, sand_raw_material):
    """Draft -> two lines (cement, sand) -> two invitations (Acme, Beta)
    -> issued. Returns (rfq_body, cement_line_id, sand_line_id)."""
    rfq = _create_rfq(client, admin_headers).json()
    cement = _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "100").json()["lines"][0]
    sand_body = _add_line(client, admin_headers, rfq["id"], sand_raw_material.id, "20", remarks="fine washed").json()
    sand = next(line for line in sand_body["lines"] if line["raw_material_id"] == sand_raw_material.id)
    _invite(client, admin_headers, rfq["id"], acme_supplier.id)
    _invite(client, admin_headers, rfq["id"], beta_supplier.id)
    issued = _issue(client, admin_headers, rfq["id"])
    assert issued.status_code == 200
    return issued.json(), cement["id"], sand["id"]


# --- numbering ----------------------------------------------------------------


def test_rfq_number_format_and_yearly_sequence(client, admin_headers):
    first = _create_rfq(client, admin_headers).json()
    second = _create_rfq(client, admin_headers).json()
    year_suffix = str(date.today().year % 100).zfill(2)
    assert first["rfq_number"] == f"{year_suffix}30001"
    assert second["rfq_number"] == f"{year_suffix}30002"


def test_rfq_number_resets_per_year(db_session, organisation):
    number_2025 = rfq_service.generate_rfq_number(db_session, organisation.id, today=date(2025, 12, 31))
    assert number_2025 == "2530001"
    db_session.add(Rfq(organisation_id=organisation.id, rfq_number=number_2025, status="draft", rfq_date=date(2025, 12, 31)))
    db_session.commit()
    assert rfq_service.generate_rfq_number(db_session, organisation.id, today=date(2026, 1, 1)) == "2630001"


# --- header ---------------------------------------------------------------------


def test_list_requires_authentication(client):
    assert client.get("/api/rfqs").status_code == 401


def test_create_stamps_requester_and_accepts_team_and_priority(client, admin_headers, admin_user, sales_team):
    response = _create_rfq(
        client, admin_headers, team_id=sales_team.id, priority="urgent", requested_by_user_id=999999
    )
    assert response.status_code == 201
    body = response.json()
    assert body["requested_by_user_id"] == admin_user.id
    assert body["team_id"] == sales_team.id
    assert body["priority"] == "urgent"
    assert body["invitations"] == []
    assert "supplier_id" not in body


def test_create_defaults_priority_and_rejects_unknown(client, admin_headers):
    assert _create_rfq(client, admin_headers).json()["priority"] == "normal"
    assert _create_rfq(client, admin_headers, priority="critical").status_code == 422


def test_team_from_another_organisation_is_rejected(client, admin_headers, db_session, other_organisation):
    other_team = Team(organisation_id=other_organisation.id, name="Buying", code="BUY", is_active=True)
    db_session.add(other_team)
    db_session.commit()
    assert _create_rfq(client, admin_headers, team_id=other_team.id).status_code == 422


def test_update_cannot_change_requester(client, admin_headers, admin_user):
    rfq = _create_rfq(client, admin_headers).json()
    response = client.patch(
        f"/api/rfqs/{rfq['id']}", json={"priority": "urgent", "requested_by_user_id": 999999}, headers=admin_headers
    )
    assert response.status_code == 200
    assert response.json()["priority"] == "urgent"
    assert response.json()["requested_by_user_id"] == admin_user.id


def test_line_remarks_are_stored_and_editable_in_draft(client, admin_headers, cement_raw_material):
    rfq = _create_rfq(client, admin_headers).json()
    line = _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "10", remarks="Type 1").json()["lines"][0]
    assert line["remarks"] == "Type 1"
    updated = client.patch(f"/api/rfqs/{rfq['id']}/lines/{line['id']}", json={"remarks": "Type 2"}, headers=admin_headers)
    assert updated.status_code == 200
    assert updated.json()["lines"][0] == {**line, "remarks": "Type 2"}


# --- invitations / issuing --------------------------------------------------------


def test_cannot_issue_without_lines_or_without_invitations(client, admin_headers, acme_supplier, cement_raw_material):
    rfq = _create_rfq(client, admin_headers).json()
    _invite(client, admin_headers, rfq["id"], acme_supplier.id)
    assert _issue(client, admin_headers, rfq["id"]).status_code == 400

    rfq2 = _create_rfq(client, admin_headers).json()
    _add_line(client, admin_headers, rfq2["id"], cement_raw_material.id, "10")
    assert _issue(client, admin_headers, rfq2["id"]).status_code == 400


def test_supplier_cannot_be_invited_twice(client, admin_headers, acme_supplier):
    rfq = _create_rfq(client, admin_headers).json()
    assert _invite(client, admin_headers, rfq["id"], acme_supplier.id).status_code == 201
    assert _invite(client, admin_headers, rfq["id"], acme_supplier.id).status_code == 409


def test_invite_rejects_inactive_or_foreign_supplier(client, admin_headers, db_session, organisation, other_organisation):
    inactive = Supplier(organisation_id=organisation.id, code="SUP0009", name="Dormant", is_active=False)
    foreign = Supplier(organisation_id=other_organisation.id, code="SUP0001", name="Elsewhere", is_active=True)
    db_session.add_all([inactive, foreign])
    db_session.commit()
    rfq = _create_rfq(client, admin_headers).json()
    assert _invite(client, admin_headers, rfq["id"], inactive.id).status_code == 422
    assert _invite(client, admin_headers, rfq["id"], foreign.id).status_code == 422


def test_invitations_are_draft_only(client, admin_headers, issued_two_supplier_rfq, db_session, organisation):
    rfq, _, _ = issued_two_supplier_rfq
    late = Supplier(organisation_id=organisation.id, code="SUP0003", name="Late Co", is_active=True)
    db_session.add(late)
    db_session.commit()
    assert _invite(client, admin_headers, rfq["id"], late.id).status_code == 400
    invitation_id = rfq["invitations"][0]["id"]
    assert client.delete(f"/api/rfqs/{rfq['id']}/invitations/{invitation_id}", headers=admin_headers).status_code == 400


def test_remove_invitation_in_draft(client, admin_headers, acme_supplier):
    rfq = _create_rfq(client, admin_headers).json()
    invitation_id = _invite(client, admin_headers, rfq["id"], acme_supplier.id).json()["invitations"][0]["id"]
    assert client.delete(f"/api/rfqs/{rfq['id']}/invitations/{invitation_id}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/rfqs/{rfq['id']}", headers=admin_headers).json()["invitations"] == []


def test_lines_not_editable_once_issued(client, admin_headers, issued_two_supplier_rfq, cement_raw_material):
    rfq, _, _ = issued_two_supplier_rfq
    assert _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "5").status_code == 400


# --- full multi-supplier flow -------------------------------------------------------


def test_full_flow_compare_select_and_convert_prefilled(
    client, admin_headers, issued_two_supplier_rfq, acme_supplier, beta_supplier, warehouse_1,
    cement_raw_material, sand_raw_material, db_session,
):
    rfq, cement_id, sand_id = issued_two_supplier_rfq
    acme_inv = _invitation_for(rfq, acme_supplier.id)
    beta_inv = _invitation_for(rfq, beta_supplier.id)
    assert acme_inv["status"] == "sent"

    file_id = _upload_file(client, admin_headers)
    acme = _capture(
        client, admin_headers, rfq["id"], acme_inv["id"],
        [{"rfq_line_id": cement_id, "unit_price": "42.000"}, {"rfq_line_id": sand_id, "unit_price": "5", "delivery_days": 3}],
        file_ids=[file_id], supplier_quotation_number="AQ-17", payment_terms="30 days",
    )
    assert acme.status_code == 201
    assert acme.json()["status"] == "response_received"
    beta = _capture(
        client, admin_headers, rfq["id"], beta_inv["id"],
        [{"rfq_line_id": cement_id, "unit_price": "39.500", "remarks": "ex-works"}, {"rfq_line_id": sand_id, "unit_price": "6"}],
    )
    assert beta.status_code == 201

    # Comparison shape: each supplier's quote per RFQ line, as stored.
    body = client.get(f"/api/rfqs/{rfq['id']}", headers=admin_headers).json()
    acme_out = _invitation_for(body, acme_supplier.id)
    beta_out = _invitation_for(body, beta_supplier.id)
    assert acme_out["status"] == beta_out["status"] == "quoted"
    acme_prices = {line["rfq_line_id"]: line["unit_price"] for line in acme_out["responses"][0]["lines"]}
    beta_prices = {line["rfq_line_id"]: line["unit_price"] for line in beta_out["responses"][0]["lines"]}
    assert acme_prices == {cement_id: "42.0000", sand_id: "5.0000"}
    assert beta_prices == {cement_id: "39.5000", sand_id: "6.0000"}
    assert acme_out["responses"][0]["files"][0]["id"] == file_id
    assert acme_out["responses"][0]["payment_terms"] == "30 days"
    assert beta_out["responses"][0]["files"] == []
    # Requested quantities are never rewritten by a response.
    assert {line["id"]: line["quantity"] for line in body["lines"]} == {cement_id: "100.0000", sand_id: "20.0000"}

    beta_response_id = beta_out["responses"][0]["id"]
    decided = _decide(client, admin_headers, rfq["id"], "selected", selected_response_id=beta_response_id)
    assert decided.status_code == 200
    assert decided.json()["selected_response_id"] == beta_response_id
    assert db_session.query(StockMovement).count() == 0

    converted = _convert(client, admin_headers, rfq["id"], warehouse_1.id)
    assert converted.status_code == 200
    final = converted.json()
    assert final["status"] == "converted"

    po = db_session.query(PurchaseOrder).filter(PurchaseOrder.id == final["purchase_order_id"]).one()
    assert po.supplier_id == beta_supplier.id
    assert po.rfq_id == rfq["id"]
    po_lines = {
        line.raw_material_id: line
        for line in db_session.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == po.id)
    }
    assert po_lines[cement_raw_material.id].unit_price == Decimal("39.5000")
    assert po_lines[cement_raw_material.id].quantity == Decimal("100.0000")
    assert po_lines[sand_raw_material.id].unit_price == Decimal("6.0000")

    assert db_session.query(StockMovement).count() == 0
    assert db_session.query(RawMaterialInventory).count() == 0


def test_convert_override_replaces_quoted_price(
    client, admin_headers, issued_two_supplier_rfq, acme_supplier, warehouse_1, cement_raw_material, db_session
):
    rfq, cement_id, sand_id = issued_two_supplier_rfq
    inv = _invitation_for(rfq, acme_supplier.id)
    body = _capture(
        client, admin_headers, rfq["id"], inv["id"],
        [{"rfq_line_id": cement_id, "unit_price": "42"}, {"rfq_line_id": sand_id, "unit_price": "5"}],
    ).json()
    response_id = _invitation_for(body, acme_supplier.id)["responses"][0]["id"]
    _decide(client, admin_headers, rfq["id"], "selected", selected_response_id=response_id)

    converted = _convert(
        client, admin_headers, rfq["id"], warehouse_1.id,
        [{"rfq_line_id": cement_id, "unit_price": "40.25"}, {"rfq_line_id": sand_id}],
    )
    assert converted.status_code == 200
    po_lines = {
        line.raw_material_id: line.unit_price
        for line in db_session.query(PurchaseOrderLine).filter(
            PurchaseOrderLine.purchase_order_id == converted.json()["purchase_order_id"]
        )
    }
    assert po_lines[cement_raw_material.id] == Decimal("40.2500")
    assert len(po_lines) == 2


def test_unquoted_line_requires_manual_price(
    client, admin_headers, issued_two_supplier_rfq, acme_supplier, warehouse_1, db_session
):
    rfq, cement_id, sand_id = issued_two_supplier_rfq
    inv = _invitation_for(rfq, acme_supplier.id)
    body = _capture(client, admin_headers, rfq["id"], inv["id"], [{"rfq_line_id": cement_id, "unit_price": "42"}]).json()
    _decide(client, admin_headers, rfq["id"], "selected", selected_response_id=_invitation_for(body, acme_supplier.id)["responses"][0]["id"])

    missing = _convert(client, admin_headers, rfq["id"], warehouse_1.id)
    assert missing.status_code == 422
    assert db_session.query(PurchaseOrder).count() == 0
    assert client.get(f"/api/rfqs/{rfq['id']}", headers=admin_headers).json()["status"] == "selected"

    ok = _convert(client, admin_headers, rfq["id"], warehouse_1.id, [{"rfq_line_id": cement_id}, {"rfq_line_id": sand_id, "unit_price": "7"}])
    assert ok.status_code == 200


def test_cannot_convert_twice(client, admin_headers, issued_two_supplier_rfq, acme_supplier, warehouse_1, db_session):
    rfq, cement_id, sand_id = issued_two_supplier_rfq
    inv = _invitation_for(rfq, acme_supplier.id)
    body = _capture(
        client, admin_headers, rfq["id"], inv["id"],
        [{"rfq_line_id": cement_id, "unit_price": "1"}, {"rfq_line_id": sand_id, "unit_price": "1"}],
    ).json()
    _decide(client, admin_headers, rfq["id"], "selected", selected_response_id=_invitation_for(body, acme_supplier.id)["responses"][0]["id"])
    assert _convert(client, admin_headers, rfq["id"], warehouse_1.id).status_code == 200
    assert _convert(client, admin_headers, rfq["id"], warehouse_1.id).status_code == 400
    assert db_session.query(PurchaseOrder).count() == 1


# --- response capture ------------------------------------------------------------------


def test_response_line_from_another_rfq_is_rejected(
    client, admin_headers, issued_two_supplier_rfq, acme_supplier, cement_raw_material, db_session
):
    rfq, _, _ = issued_two_supplier_rfq
    other = _create_rfq(client, admin_headers).json()
    foreign_line_id = _add_line(client, admin_headers, other["id"], cement_raw_material.id, "1").json()["lines"][0]["id"]
    inv = _invitation_for(rfq, acme_supplier.id)
    response = _capture(client, admin_headers, rfq["id"], inv["id"], [{"rfq_line_id": foreign_line_id, "unit_price": "1"}])
    assert response.status_code == 422
    assert db_session.query(RfqResponse).count() == 0
    assert client.get(f"/api/rfqs/{rfq['id']}", headers=admin_headers).json()["status"] == "issued"


def test_response_validation(client, admin_headers, issued_two_supplier_rfq, acme_supplier):
    rfq, cement_id, _ = issued_two_supplier_rfq
    inv = _invitation_for(rfq, acme_supplier.id)
    assert _capture(client, admin_headers, rfq["id"], inv["id"], []).status_code == 422
    assert _capture(client, admin_headers, rfq["id"], inv["id"], [{"rfq_line_id": cement_id, "unit_price": "0"}]).status_code == 422
    duplicate = [{"rfq_line_id": cement_id, "unit_price": "1"}, {"rfq_line_id": cement_id, "unit_price": "2"}]
    assert _capture(client, admin_headers, rfq["id"], inv["id"], duplicate).status_code == 422


def test_cannot_capture_before_issue(client, admin_headers, acme_supplier, cement_raw_material):
    rfq = _create_rfq(client, admin_headers).json()
    line_id = _add_line(client, admin_headers, rfq["id"], cement_raw_material.id, "1").json()["lines"][0]["id"]
    inv_id = _invite(client, admin_headers, rfq["id"], acme_supplier.id).json()["invitations"][0]["id"]
    assert _capture(client, admin_headers, rfq["id"], inv_id, [{"rfq_line_id": line_id, "unit_price": "1"}]).status_code == 400


def test_invitations_capture_and_revise_independently(
    client, admin_headers, issued_two_supplier_rfq, acme_supplier, beta_supplier, db_session
):
    rfq, cement_id, _ = issued_two_supplier_rfq
    acme_inv = _invitation_for(rfq, acme_supplier.id)
    beta_inv = _invitation_for(rfq, beta_supplier.id)

    _capture(client, admin_headers, rfq["id"], acme_inv["id"], [{"rfq_line_id": cement_id, "unit_price": "42"}])
    _capture(client, admin_headers, rfq["id"], beta_inv["id"], [{"rfq_line_id": cement_id, "unit_price": "40"}])
    revised = _capture(client, admin_headers, rfq["id"], acme_inv["id"], [{"rfq_line_id": cement_id, "unit_price": "38"}])
    assert revised.status_code == 201

    body = revised.json()
    acme_history = [r["lines"][0]["unit_price"] for r in _invitation_for(body, acme_supplier.id)["responses"]]
    beta_history = [r["lines"][0]["unit_price"] for r in _invitation_for(body, beta_supplier.id)["responses"]]
    assert acme_history == ["42.0000", "38.0000"]
    assert beta_history == ["40.0000"]
    assert db_session.query(RfqResponseLine).count() == 3


def test_decline_is_a_flag_only(client, admin_headers, issued_two_supplier_rfq, acme_supplier, beta_supplier):
    rfq, cement_id, _ = issued_two_supplier_rfq
    acme_inv = _invitation_for(rfq, acme_supplier.id)
    beta_inv = _invitation_for(rfq, beta_supplier.id)

    declined = _decline(client, admin_headers, rfq["id"], beta_inv["id"])
    assert declined.status_code == 200
    body = declined.json()
    assert body["status"] == "issued"
    assert _invitation_for(body, beta_supplier.id)["status"] == "declined"
    assert _invitation_for(body, acme_supplier.id)["status"] == "sent"

    # Declining twice, or declining a supplier that already quoted, is refused.
    assert _decline(client, admin_headers, rfq["id"], beta_inv["id"]).status_code == 400
    _capture(client, admin_headers, rfq["id"], acme_inv["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}])
    assert _decline(client, admin_headers, rfq["id"], acme_inv["id"]).status_code == 400


def test_attachments_are_optional_and_org_scoped(client, admin_headers, other_admin_headers, issued_two_supplier_rfq, acme_supplier):
    rfq, cement_id, _ = issued_two_supplier_rfq
    inv = _invitation_for(rfq, acme_supplier.id)
    other_file_id = _upload_file(client, other_admin_headers)
    response = _capture(client, admin_headers, rfq["id"], inv["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}], file_ids=[other_file_id])
    assert response.status_code == 422


# --- decision / rejection / cancellation ---------------------------------------------


def test_decision_requires_a_captured_response(client, admin_headers, issued_two_supplier_rfq):
    rfq, _, _ = issued_two_supplier_rfq
    assert _decide(client, admin_headers, rfq["id"], "rejected").status_code == 400


def test_cannot_select_a_response_from_another_rfq(
    client, admin_headers, issued_two_supplier_rfq, acme_supplier, cement_raw_material
):
    rfq, cement_id, _ = issued_two_supplier_rfq
    inv = _invitation_for(rfq, acme_supplier.id)
    _capture(client, admin_headers, rfq["id"], inv["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}])

    other = _create_rfq(client, admin_headers).json()
    other_line = _add_line(client, admin_headers, other["id"], cement_raw_material.id, "1").json()["lines"][0]["id"]
    other_inv = _invite(client, admin_headers, other["id"], acme_supplier.id).json()["invitations"][0]["id"]
    _issue(client, admin_headers, other["id"])
    other_body = _capture(client, admin_headers, other["id"], other_inv, [{"rfq_line_id": other_line, "unit_price": "1"}]).json()
    foreign_response_id = other_body["invitations"][0]["responses"][0]["id"]

    assert _decide(client, admin_headers, rfq["id"], "selected", selected_response_id=foreign_response_id).status_code == 422
    assert _decide(client, admin_headers, rfq["id"], "selected", selected_response_id=None).status_code == 422


def test_rejected_rfq_has_no_convert_path(client, admin_headers, issued_two_supplier_rfq, acme_supplier, warehouse_1):
    rfq, cement_id, _ = issued_two_supplier_rfq
    inv = _invitation_for(rfq, acme_supplier.id)
    _capture(client, admin_headers, rfq["id"], inv["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}])
    rejected = _decide(client, admin_headers, rfq["id"], "rejected")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert _convert(client, admin_headers, rfq["id"], warehouse_1.id).status_code == 400


def test_cancel_requires_reason(client, admin_headers, issued_two_supplier_rfq):
    rfq, _, _ = issued_two_supplier_rfq
    no_reason = client.patch(f"/api/rfqs/{rfq['id']}/status", json={"status": "cancelled"}, headers=admin_headers)
    assert no_reason.status_code == 422
    cancelled = _cancel(client, admin_headers, rfq["id"])
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


# --- list / organisation isolation ------------------------------------------------------


def test_list_filters_by_invited_supplier_and_priority(client, admin_headers, acme_supplier, beta_supplier):
    acme_rfq = _create_rfq(client, admin_headers, priority="urgent").json()
    _invite(client, admin_headers, acme_rfq["id"], acme_supplier.id)
    beta_rfq = _create_rfq(client, admin_headers).json()
    _invite(client, admin_headers, beta_rfq["id"], beta_supplier.id)

    by_supplier = client.get("/api/rfqs", params={"supplier_id": acme_supplier.id}, headers=admin_headers).json()
    assert [r["id"] for r in by_supplier["data"]] == [acme_rfq["id"]]
    by_priority = client.get("/api/rfqs", params={"priority": "normal"}, headers=admin_headers).json()
    assert [r["id"] for r in by_priority["data"]] == [beta_rfq["id"]]
    assert client.get("/api/rfqs", params={"priority": "whatever"}, headers=admin_headers).status_code == 422


def test_cross_organisation_rfq_and_comparison_never_leak(
    client, admin_headers, other_admin_headers, issued_two_supplier_rfq, acme_supplier
):
    rfq, cement_id, _ = issued_two_supplier_rfq
    inv = _invitation_for(rfq, acme_supplier.id)
    _capture(client, admin_headers, rfq["id"], inv["id"], [{"rfq_line_id": cement_id, "unit_price": "42"}])

    assert client.get(f"/api/rfqs/{rfq['id']}", headers=other_admin_headers).status_code == 404
    assert client.get("/api/rfqs", headers=other_admin_headers).json()["data"] == []
    assert (
        _capture(client, other_admin_headers, rfq["id"], inv["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}]).status_code
        == 404
    )
    assert _decline(client, other_admin_headers, rfq["id"], inv["id"]).status_code == 404


def test_invitation_must_belong_to_the_rfq_in_the_path(client, admin_headers, issued_two_supplier_rfq, acme_supplier, cement_raw_material):
    rfq, cement_id, _ = issued_two_supplier_rfq
    other = _create_rfq(client, admin_headers).json()
    other_inv = _invite(client, admin_headers, other["id"], acme_supplier.id).json()["invitations"][0]["id"]
    response = _capture(client, admin_headers, rfq["id"], other_inv, [{"rfq_line_id": cement_id, "unit_price": "1"}])
    assert response.status_code == 404


# --- permissions ------------------------------------------------------------------------


def test_team_member_denied_by_default(client, active_user):
    headers = _login_headers(client)
    assert client.get("/api/rfqs", headers=headers).status_code == 403
