"""Tests for docs/modules/rfq.md: RFQ form (draft / submit / revise) with
mandatory items in a convertible unit and registered suppliers, one
letterhead PDF per supplier (download + email), structured quote capture,
accept-with-uploaded-quotation or reject, and conversion to a Purchase
Order in the material's own unit. Plus numbering, the inventory boundary,
organisation isolation and permissions."""
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from PIL import Image

from app.core.security import hash_password
from app.models.inventory import RawMaterialInventory, StockMovement
from app.models.purchase_order import PurchaseOrder, PurchaseOrderLine
from app.models.raw_material import RawMaterial
from app.models.rfq import Rfq, RfqResponse, RfqResponseLine
from app.models.supplier import Supplier
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.services import email_service, rfq_service

PDF_BYTES = b"%PDF-1.4 fake supplier quote"
FUTURE = (date.today() + timedelta(days=30)).isoformat()


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _upload(client, headers, name="quote.pdf", content=PDF_BYTES, mime="application/pdf"):
    response = client.post("/api/files", headers=headers, files={"upload": (name, io.BytesIO(content), mime)})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (60, 85), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def _form(supplier_ids, lines, submit=True, **extra):
    return {
        "required_delivery_date": FUTURE,
        "priority": "normal",
        "supplier_ids": supplier_ids,
        "lines": lines,
        "submit": submit,
        **extra,
    }


def _line(material, unit_id=None, quantity="10", **extra):
    return {"raw_material_id": material.id, "unit_of_measure_id": unit_id or material.unit_of_measure_id, "quantity": quantity, **extra}


def _create(client, headers, body):
    return client.post("/api/rfqs", json=body, headers=headers)


def _capture(client, headers, rfq_id, invitation_id, lines, file_ids=None, **extra):
    return client.post(
        f"/api/rfqs/{rfq_id}/invitations/{invitation_id}/responses",
        json={"lines": lines, "file_ids": file_ids or [], "response_received_at": datetime.utcnow().isoformat(), **extra},
        headers=headers,
    )


def _accept(client, headers, rfq_id, response_id, file_ids, quantities_confirmed=True):
    return client.patch(
        f"/api/rfqs/{rfq_id}/decision",
        json={
            "decision": "selected", "selected_response_id": response_id,
            "file_ids": file_ids, "quantities_confirmed": quantities_confirmed,
        },
        headers=headers,
    )


def _reject(client, headers, rfq_id):
    return client.patch(f"/api/rfqs/{rfq_id}/decision", json={"decision": "rejected"}, headers=headers)


def _convert(client, headers, rfq_id, warehouse_id, lines=None, **extra):
    body = {"warehouse_id": warehouse_id, "expected_delivery_date": FUTURE, "payment_terms": "30 days", **extra}
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
    supplier = Supplier(
        organisation_id=organisation.id, code="SUP0002", name="Beta Supplies", email="sales@beta.example", is_active=True
    )
    db_session.add(supplier)
    db_session.commit()
    db_session.refresh(supplier)
    return supplier


@pytest.fixture()
def sand_raw_material(db_session, organisation, electronics_category, kilogram_unit):
    material = RawMaterial(
        organisation_id=organisation.id, code="RM002", name="Sand",
        category_id=electronics_category.id, unit_of_measure_id=kilogram_unit.id, is_active=True,
    )
    db_session.add(material)
    db_session.commit()
    db_session.refresh(material)
    return material


@pytest.fixture()
def tonne_unit(db_session, organisation):
    unit = UnitOfMeasure(
        organisation_id=organisation.id, name="Metric Tonne", code="MT", dimension="mass",
        conversion_factor_to_base=1000, is_active=True,
    )
    db_session.add(unit)
    db_session.commit()
    db_session.refresh(unit)
    return unit


@pytest.fixture()
def gravel_raw_material(db_session, organisation, electronics_category, mass_kilogram_unit):
    material = RawMaterial(
        organisation_id=organisation.id, code="RM003", name="Gravel",
        category_id=electronics_category.id, unit_of_measure_id=mass_kilogram_unit.id, is_active=True,
    )
    db_session.add(material)
    db_session.commit()
    db_session.refresh(material)
    return material


@pytest.fixture()
def other_admin_headers(client, db_session, other_org_user):
    db_session.add(
        User(
            organisation_id=other_org_user.organisation_id, role="admin", full_name="Other Admin",
            email="other-admin@example.com", username="other_admin",
            password_hash=hash_password("Str0ng!Pass"), is_active=True,
        )
    )
    db_session.commit()
    return _login_headers(client, "other_admin")


@pytest.fixture()
def issued_rfq(client, admin_headers, acme_supplier, beta_supplier, cement_raw_material, sand_raw_material):
    """Submitted RFQ: cement 100 + sand 20 (remarks), to Acme and Beta.
    Returns (rfq_body, cement_line_id, sand_line_id)."""
    response = _create(
        client, admin_headers,
        _form(
            [acme_supplier.id, beta_supplier.id],
            [_line(cement_raw_material, quantity="100"), _line(sand_raw_material, quantity="20", remarks="fine washed")],
        ),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    lines = {line["raw_material_id"]: line["id"] for line in body["lines"]}
    return body, lines[cement_raw_material.id], lines[sand_raw_material.id]


def _quote_and_accept(client, headers, rfq, supplier_id, prices):
    invitation = _invitation_for(rfq, supplier_id)
    body = _capture(client, headers, rfq["id"], invitation["id"], [{"rfq_line_id": k, "unit_price": v} for k, v in prices.items()]).json()
    response_id = _invitation_for(body, supplier_id)["responses"][-1]["id"]
    accepted = _accept(client, headers, rfq["id"], response_id, [_upload(client, headers)])
    assert accepted.status_code == 200, accepted.text
    return accepted.json()


# --- numbering ----------------------------------------------------------------


def test_rfq_number_format_and_yearly_sequence(client, admin_headers, acme_supplier, cement_raw_material):
    body = _form([acme_supplier.id], [_line(cement_raw_material)], submit=False)
    first = _create(client, admin_headers, body).json()
    second = _create(client, admin_headers, body).json()
    year_suffix = str(date.today().year % 100).zfill(2)
    assert first["rfq_number"] == f"{year_suffix}30001"
    assert second["rfq_number"] == f"{year_suffix}30002"


def test_next_number_preview(client, admin_headers, acme_supplier, cement_raw_material):
    first = client.get("/api/rfqs/next-number", headers=admin_headers).json()["rfq_number"]
    created = _create(client, admin_headers, _form([acme_supplier.id], [_line(cement_raw_material)], submit=False)).json()
    assert created["rfq_number"] == first
    assert client.get("/api/rfqs/next-number", headers=admin_headers).json()["rfq_number"] != first


def test_rfq_number_resets_per_year(db_session, organisation):
    assert rfq_service.generate_rfq_number(db_session, organisation.id, today=date(2025, 12, 31)) == "2530001"
    db_session.add(Rfq(organisation_id=organisation.id, rfq_number="2530001", status="draft", rfq_date=date(2025, 12, 31)))
    db_session.commit()
    assert rfq_service.generate_rfq_number(db_session, organisation.id, today=date(2026, 1, 1)) == "2630001"


# --- the RFQ form -----------------------------------------------------------------


def test_list_requires_authentication(client):
    assert client.get("/api/rfqs").status_code == 401


def test_save_draft_stamps_auto_fields_and_generates_no_pdf(
    client, admin_headers, admin_user, acme_supplier, cement_raw_material
):
    response = _create(
        client, admin_headers,
        _form([acme_supplier.id], [_line(cement_raw_material, remarks="Type 1")], submit=False,
              requested_by_user_id=999999, rfq_date="2020-01-01"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["revision_number"] == 0
    assert body["rfq_date"] == date.today().isoformat()
    assert body["requested_by_user_id"] == admin_user.id
    assert body["lines"][0]["unit_of_measure_id"] == cement_raw_material.unit_of_measure_id
    assert body["lines"][0]["remarks"] == "Type 1"
    assert body["invitations"][0]["pdf_file"] is None


def test_submit_issues_revision_1_with_one_pdf_per_supplier(client, admin_headers, issued_rfq):
    rfq, _, _ = issued_rfq
    assert rfq["status"] == "issued"
    assert rfq["revision_number"] == 1
    assert len(rfq["invitations"]) == 2
    for invitation in rfq["invitations"]:
        pdf = invitation["pdf_file"]
        assert pdf["mime_type"] == "application/pdf"
        download = client.get(f"/api/files/{pdf['id']}", headers=admin_headers)
        assert download.status_code == 200
        assert download.content.startswith(b"%PDF")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body.update(lines=[]),
        lambda body: body["lines"][0].update(quantity="0"),
        lambda body: body["lines"][0].pop("unit_of_measure_id"),
        lambda body: body.update(supplier_ids=[]),
        lambda body: body.update(supplier_ids=body["supplier_ids"] * 2),
        lambda body: body.pop("required_delivery_date"),
        lambda body: body.update(required_delivery_date=(date.today() - timedelta(days=1)).isoformat()),
        lambda body: body.update(priority="critical"),
    ],
)
def test_form_rules_are_enforced(client, admin_headers, acme_supplier, cement_raw_material, mutate):
    body = _form([acme_supplier.id], [_line(cement_raw_material)])
    mutate(body)
    assert _create(client, admin_headers, body).status_code == 422


def test_suppliers_and_materials_must_be_active_and_own_organisation(
    client, admin_headers, db_session, organisation, other_organisation, cement_raw_material
):
    dormant = Supplier(organisation_id=organisation.id, code="SUP0009", name="Dormant", is_active=False)
    foreign = Supplier(organisation_id=other_organisation.id, code="SUP0001", name="Elsewhere", is_active=True)
    db_session.add_all([dormant, foreign])
    db_session.commit()
    line = [_line(cement_raw_material)]
    assert _create(client, admin_headers, _form([dormant.id], line)).status_code == 422
    assert _create(client, admin_headers, _form([foreign.id], line)).status_code == 422

    active = Supplier(organisation_id=organisation.id, code="SUP0010", name="Active", is_active=True)
    db_session.add(active)
    db_session.commit()
    assert _create(client, admin_headers, _form([active.id], line)).status_code == 201
    assert _create(client, admin_headers, _form([active.id], [{**line[0], "raw_material_id": 999999}])).status_code == 422


def test_unit_must_convert_to_the_material_unit(
    client, admin_headers, acme_supplier, cement_raw_material, gravel_raw_material, tonne_unit
):
    # Cement is in plain KG (no dimension) -- tonnes cannot be converted.
    bad = _create(client, admin_headers, _form([acme_supplier.id], [_line(cement_raw_material, tonne_unit.id)]))
    assert bad.status_code == 422
    # Gravel is in mass KG -- tonnes convert.
    ok = _create(client, admin_headers, _form([acme_supplier.id], [_line(gravel_raw_material, tonne_unit.id, "2")]))
    assert ok.status_code == 201


# --- draft editing and revisions ---------------------------------------------------


def test_draft_can_be_edited_then_submitted(
    client, admin_headers, acme_supplier, beta_supplier, cement_raw_material, sand_raw_material
):
    draft = _create(client, admin_headers, _form([acme_supplier.id], [_line(cement_raw_material)], submit=False)).json()
    edited = client.put(
        f"/api/rfqs/{draft['id']}",
        json=_form([beta_supplier.id], [_line(sand_raw_material, quantity="5")], submit=False),
        headers=admin_headers,
    ).json()
    assert edited["status"] == "draft"
    assert [i["supplier_id"] for i in edited["invitations"]] == [beta_supplier.id]
    assert [(l["raw_material_id"], l["quantity"]) for l in edited["lines"]] == [(sand_raw_material.id, "5.0000")]

    submitted = client.put(
        f"/api/rfqs/{draft['id']}",
        json=_form([beta_supplier.id], [_line(sand_raw_material, quantity="5")]),
        headers=admin_headers,
    ).json()
    assert submitted["status"] == "issued"
    assert submitted["revision_number"] == 1
    assert submitted["invitations"][0]["pdf_file"] is not None


def test_issued_rfq_revises_to_next_revision_until_first_quote(
    client, admin_headers, db_session, issued_rfq, acme_supplier, cement_raw_material
):
    rfq, cement_id, _ = issued_rfq
    acme_first_pdf = _invitation_for(rfq, acme_supplier.id)["pdf_file"]["id"]

    # Saving an issued RFQ without submitting a new revision is refused.
    body = _form([acme_supplier.id], [_line(cement_raw_material, quantity="150")], submit=False)
    assert client.put(f"/api/rfqs/{rfq['id']}", json=body, headers=admin_headers).status_code == 400

    revised = client.put(f"/api/rfqs/{rfq['id']}", json={**body, "submit": True}, headers=admin_headers)
    assert revised.status_code == 200
    revised_body = revised.json()
    assert revised_body["revision_number"] == 2
    assert [i["supplier_id"] for i in revised_body["invitations"]] == [acme_supplier.id]
    acme = revised_body["invitations"][0]
    assert acme["pdf_file"]["id"] != acme_first_pdf
    # Earlier revision's PDF is kept, still downloadable.
    assert client.get(f"/api/files/{acme_first_pdf}", headers=admin_headers).status_code == 200

    new_line = revised_body["lines"][0]["id"]
    _capture(client, admin_headers, rfq["id"], acme["id"], [{"rfq_line_id": new_line, "unit_price": "1"}])
    assert client.put(f"/api/rfqs/{rfq['id']}", json={**body, "submit": True}, headers=admin_headers).status_code == 400


# --- letterhead template -------------------------------------------------------------


def test_admin_letterhead_template_is_used_for_new_pdfs(
    client, admin_headers, acme_supplier, cement_raw_material
):
    letterhead_id = _upload(client, admin_headers, "letterhead.png", _png_bytes(), "image/png")
    saved = client.put(
        "/api/document-templates/rfq",
        json={"letterhead_file_id": letterhead_id, "margin_top_mm": 45, "margin_bottom_mm": 30,
              "intro_text": "Dear Sir,\nPlease quote.", "terms_text": "Prices in KWD.", "signature_text": "Purchasing"},
        headers=admin_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["letterhead_file"]["id"] == letterhead_id
    assert client.get("/api/document-templates/rfq", headers=admin_headers).json()["intro_text"] == "Dear Sir,\nPlease quote."

    rfq = _create(client, admin_headers, _form([acme_supplier.id], [_line(cement_raw_material)])).json()
    pdf_id = rfq["invitations"][0]["pdf_file"]["id"]
    assert client.get(f"/api/files/{pdf_id}", headers=admin_headers).content.startswith(b"%PDF")


def test_letterhead_must_be_an_image_and_template_is_admin_only(client, admin_headers, active_user):
    pdf_id = _upload(client, admin_headers)
    assert client.put("/api/document-templates/rfq", json={"letterhead_file_id": pdf_id}, headers=admin_headers).status_code == 422
    assert client.get("/api/document-templates/rfq", headers=_login_headers(client)).status_code == 403


# --- email ------------------------------------------------------------------------------


def test_email_sends_the_supplier_pdf(client, admin_headers, issued_rfq, beta_supplier, monkeypatch):
    rfq, _, _ = issued_rfq
    sent = {}

    def fake_send(db, organisation_id, to_email, subject, body, attachment, filename):
        sent.update(to=to_email, subject=subject, attachment=attachment, filename=filename)

    monkeypatch.setattr(email_service, "send_email", fake_send)
    invitation = _invitation_for(rfq, beta_supplier.id)
    response = client.post(f"/api/rfqs/{rfq['id']}/invitations/{invitation['id']}/send", headers=admin_headers)
    assert response.status_code == 200
    assert sent["to"] == "sales@beta.example"
    assert sent["attachment"].startswith(b"%PDF")
    assert rfq["rfq_number"] in sent["subject"]
    assert _invitation_for(response.json(), beta_supplier.id)["last_emailed_at"] is not None


def test_email_requires_supplier_email_and_a_configured_mailbox(client, admin_headers, issued_rfq, acme_supplier, beta_supplier):
    rfq, _, _ = issued_rfq
    no_email = _invitation_for(rfq, acme_supplier.id)
    assert client.post(f"/api/rfqs/{rfq['id']}/invitations/{no_email['id']}/send", headers=admin_headers).status_code == 422
    no_mailbox = _invitation_for(rfq, beta_supplier.id)
    assert client.post(f"/api/rfqs/{rfq['id']}/invitations/{no_mailbox['id']}/send", headers=admin_headers).status_code == 400


def test_draft_cannot_be_emailed(client, admin_headers, beta_supplier, cement_raw_material):
    draft = _create(client, admin_headers, _form([beta_supplier.id], [_line(cement_raw_material)], submit=False)).json()
    invitation_id = draft["invitations"][0]["id"]
    assert client.post(f"/api/rfqs/{draft['id']}/invitations/{invitation_id}/send", headers=admin_headers).status_code == 400


# --- quote capture -------------------------------------------------------------------------


def test_cannot_capture_a_quote_on_a_draft(client, admin_headers, acme_supplier, cement_raw_material):
    draft = _create(client, admin_headers, _form([acme_supplier.id], [_line(cement_raw_material)], submit=False)).json()
    response = _capture(client, admin_headers, draft["id"], draft["invitations"][0]["id"], [{"rfq_line_id": draft["lines"][0]["id"], "unit_price": "1"}])
    assert response.status_code == 400


def test_quote_line_from_another_rfq_is_rejected(client, admin_headers, issued_rfq, acme_supplier, cement_raw_material, db_session):
    rfq, _, _ = issued_rfq
    other = _create(client, admin_headers, _form([acme_supplier.id], [_line(cement_raw_material)])).json()
    invitation = _invitation_for(rfq, acme_supplier.id)
    response = _capture(client, admin_headers, rfq["id"], invitation["id"], [{"rfq_line_id": other["lines"][0]["id"], "unit_price": "1"}])
    assert response.status_code == 422
    assert db_session.query(RfqResponse).count() == 0


def test_quote_validation(client, admin_headers, issued_rfq, acme_supplier):
    rfq, cement_id, _ = issued_rfq
    invitation_id = _invitation_for(rfq, acme_supplier.id)["id"]
    assert _capture(client, admin_headers, rfq["id"], invitation_id, []).status_code == 422
    assert _capture(client, admin_headers, rfq["id"], invitation_id, [{"rfq_line_id": cement_id, "unit_price": "0"}]).status_code == 422


def test_suppliers_quote_and_revise_independently(client, admin_headers, issued_rfq, acme_supplier, beta_supplier, db_session):
    rfq, cement_id, _ = issued_rfq
    acme = _invitation_for(rfq, acme_supplier.id)["id"]
    beta = _invitation_for(rfq, beta_supplier.id)["id"]
    _capture(client, admin_headers, rfq["id"], acme, [{"rfq_line_id": cement_id, "unit_price": "42"}])
    _capture(client, admin_headers, rfq["id"], beta, [{"rfq_line_id": cement_id, "unit_price": "40"}])
    body = _capture(client, admin_headers, rfq["id"], acme, [{"rfq_line_id": cement_id, "unit_price": "38"}]).json()
    assert body["status"] == "response_received"
    assert [r["lines"][0]["unit_price"] for r in _invitation_for(body, acme_supplier.id)["responses"]] == ["42.0000", "38.0000"]
    assert [r["lines"][0]["unit_price"] for r in _invitation_for(body, beta_supplier.id)["responses"]] == ["40.0000"]
    assert db_session.query(RfqResponseLine).count() == 3


def test_decline_is_a_flag_only(client, admin_headers, issued_rfq, acme_supplier, beta_supplier):
    rfq, _, _ = issued_rfq
    beta = _invitation_for(rfq, beta_supplier.id)
    body = client.post(f"/api/rfqs/{rfq['id']}/invitations/{beta['id']}/decline", headers=admin_headers).json()
    assert body["status"] == "issued"
    assert _invitation_for(body, beta_supplier.id)["status"] == "declined"
    assert _invitation_for(body, acme_supplier.id)["status"] == "sent"


# --- accept / reject -------------------------------------------------------------------------


def test_accept_requires_an_uploaded_pdf_or_image(client, admin_headers, issued_rfq, acme_supplier):
    rfq, cement_id, _ = issued_rfq
    invitation = _invitation_for(rfq, acme_supplier.id)
    body = _capture(client, admin_headers, rfq["id"], invitation["id"], [{"rfq_line_id": cement_id, "unit_price": "42"}]).json()
    response_id = _invitation_for(body, acme_supplier.id)["responses"][0]["id"]

    assert _accept(client, admin_headers, rfq["id"], response_id, []).status_code == 422
    csv_id = _upload(client, admin_headers, "quote.csv", b"a,b\n1,2\n", "text/csv")
    assert _accept(client, admin_headers, rfq["id"], response_id, [csv_id]).status_code == 422

    image_id = _upload(client, admin_headers, "signed.png", _png_bytes(), "image/png")
    accepted = _accept(client, admin_headers, rfq["id"], response_id, [image_id])
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "selected"
    assert [f["id"] for f in accepted.json()["acceptance_files"]] == [image_id]


def test_reject_stops_the_flow(client, admin_headers, issued_rfq, acme_supplier, warehouse_1):
    rfq, cement_id, _ = issued_rfq
    invitation = _invitation_for(rfq, acme_supplier.id)
    _capture(client, admin_headers, rfq["id"], invitation["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}])
    rejected = _reject(client, admin_headers, rfq["id"])
    assert rejected.json()["status"] == "rejected"
    assert _convert(client, admin_headers, rfq["id"], warehouse_1.id).status_code == 400
    assert _capture(client, admin_headers, rfq["id"], invitation["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}]).status_code == 400
    assert _reject(client, admin_headers, rfq["id"]).status_code == 400
    cancel = client.patch(f"/api/rfqs/{rfq['id']}/status", json={"status": "cancelled", "cancel_reason": "x"}, headers=admin_headers)
    assert cancel.status_code == 400


def test_selecting_another_rfqs_quote_is_rejected(client, admin_headers, issued_rfq, acme_supplier, cement_raw_material):
    rfq, cement_id, _ = issued_rfq
    _capture(client, admin_headers, rfq["id"], _invitation_for(rfq, acme_supplier.id)["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}])
    other = _create(client, admin_headers, _form([acme_supplier.id], [_line(cement_raw_material)])).json()
    other_body = _capture(client, admin_headers, other["id"], other["invitations"][0]["id"], [{"rfq_line_id": other["lines"][0]["id"], "unit_price": "1"}]).json()
    foreign_response = other_body["invitations"][0]["responses"][0]["id"]
    assert _accept(client, admin_headers, rfq["id"], foreign_response, [_upload(client, admin_headers)]).status_code == 422


def test_approval_requires_confirmed_quantities(client, admin_headers, issued_rfq, acme_supplier):
    rfq, cement_id, _ = issued_rfq
    body = _capture(client, admin_headers, rfq["id"], _invitation_for(rfq, acme_supplier.id)["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}]).json()
    response_id = _invitation_for(body, acme_supplier.id)["responses"][0]["id"]
    refused = _accept(client, admin_headers, rfq["id"], response_id, [_upload(client, admin_headers)], quantities_confirmed=False)
    assert refused.status_code == 422


def test_different_agreed_quantity_raises_a_new_rfq(
    client, admin_headers, issued_rfq, acme_supplier, beta_supplier
):
    rfq, cement_id, sand_id = issued_rfq
    _capture(client, admin_headers, rfq["id"], _invitation_for(rfq, acme_supplier.id)["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}])

    same = client.post(f"/api/rfqs/{rfq['id']}/raise-new", json={"lines": [{"rfq_line_id": cement_id, "quantity": "100"}]}, headers=admin_headers)
    assert same.status_code == 400

    raised = client.post(f"/api/rfqs/{rfq['id']}/raise-new", json={"lines": [{"rfq_line_id": cement_id, "quantity": "80"}]}, headers=admin_headers)
    assert raised.status_code == 201, raised.text
    new = raised.json()
    assert new["status"] == "draft"
    assert new["rfq_number"] != rfq["rfq_number"]
    assert sorted(l["quantity"] for l in new["lines"]) == ["20.0000", "80.0000"]
    assert sorted(i["supplier_id"] for i in new["invitations"]) == sorted([acme_supplier.id, beta_supplier.id])

    old = client.get(f"/api/rfqs/{rfq['id']}", headers=admin_headers).json()
    assert old["status"] == "cancelled"
    assert new["rfq_number"] in old["cancel_reason"]


def test_approved_rfq_cannot_be_revised_only_cancelled(client, admin_headers, issued_rfq, acme_supplier, cement_raw_material):
    rfq, cement_id, sand_id = issued_rfq
    _quote_and_accept(client, admin_headers, rfq, acme_supplier.id, {cement_id: "1", sand_id: "1"})
    body = _form([acme_supplier.id], [_line(cement_raw_material)])
    assert client.put(f"/api/rfqs/{rfq['id']}", json=body, headers=admin_headers).status_code == 400
    cancelled = client.patch(f"/api/rfqs/{rfq['id']}/status", json={"status": "cancelled", "cancel_reason": "Supplier withdrew"}, headers=admin_headers)
    assert cancelled.json()["status"] == "cancelled"


# --- purchase order --------------------------------------------------------------------------


def test_po_generation_requires_terms_and_keeps_agreed_terms(client, admin_headers, issued_rfq, acme_supplier, warehouse_1, db_session):
    rfq, cement_id, sand_id = issued_rfq
    _quote_and_accept(client, admin_headers, rfq, acme_supplier.id, {cement_id: "1", sand_id: "1"})
    assert _convert(client, admin_headers, rfq["id"], warehouse_1.id, payment_terms=" ").status_code == 422
    past = (date.today() - timedelta(days=1)).isoformat()
    assert _convert(client, admin_headers, rfq["id"], warehouse_1.id, expected_delivery_date=past).status_code == 422
    ok = _convert(client, admin_headers, rfq["id"], warehouse_1.id, payment_terms="Advance", supplier_reference="AQ-17")
    assert ok.status_code == 200, ok.text
    po = db_session.query(PurchaseOrder).one()
    assert (po.payment_terms, po.supplier_reference, po.expected_delivery_date.isoformat()) == ("Advance", "AQ-17", FUTURE)


def test_full_flow_to_purchase_order(
    client, admin_headers, issued_rfq, acme_supplier, beta_supplier, warehouse_1, cement_raw_material, sand_raw_material, db_session
):
    rfq, cement_id, sand_id = issued_rfq
    _capture(client, admin_headers, rfq["id"], _invitation_for(rfq, acme_supplier.id)["id"],
             [{"rfq_line_id": cement_id, "unit_price": "42"}, {"rfq_line_id": sand_id, "unit_price": "5"}])
    _quote_and_accept(client, admin_headers, rfq, beta_supplier.id, {cement_id: "39.5", sand_id: "6"})
    assert db_session.query(StockMovement).count() == 0

    converted = _convert(client, admin_headers, rfq["id"], warehouse_1.id)
    assert converted.status_code == 200, converted.text
    po = db_session.query(PurchaseOrder).filter(PurchaseOrder.id == converted.json()["purchase_order_id"]).one()
    assert po.supplier_id == beta_supplier.id
    prices = {l.raw_material_id: (l.quantity, l.unit_price) for l in db_session.query(PurchaseOrderLine).filter(PurchaseOrderLine.purchase_order_id == po.id)}
    assert prices[cement_raw_material.id] == (Decimal("100.0000"), Decimal("39.5000"))
    assert prices[sand_raw_material.id] == (Decimal("20.0000"), Decimal("6.0000"))
    assert db_session.query(StockMovement).count() == 0
    assert db_session.query(RawMaterialInventory).count() == 0
    assert _convert(client, admin_headers, rfq["id"], warehouse_1.id).status_code == 400
    assert db_session.query(PurchaseOrder).count() == 1


def test_po_keeps_the_agreed_unit_and_price(
    client, admin_headers, acme_supplier, gravel_raw_material, tonne_unit, warehouse_1, db_session
):
    rfq = _create(client, admin_headers, _form([acme_supplier.id], [_line(gravel_raw_material, tonne_unit.id, "2")])).json()
    _quote_and_accept(client, admin_headers, rfq, acme_supplier.id, {rfq["lines"][0]["id"]: "85"})
    converted = _convert(client, admin_headers, rfq["id"], warehouse_1.id)
    assert converted.status_code == 200, converted.text
    line = db_session.query(PurchaseOrderLine).one()
    assert (line.quantity, line.unit_of_measure_id, line.unit_price, line.conversion_factor) == (
        Decimal("2.0000"), tonne_unit.id, Decimal("85.0000"), Decimal("1000.000000"),
    )
    po = db_session.query(PurchaseOrder).one()
    assert po.rfq_response_id == converted.json()["selected_response_id"]


def test_convert_override_and_unquoted_lines(client, admin_headers, issued_rfq, acme_supplier, warehouse_1, cement_raw_material, db_session):
    rfq, cement_id, sand_id = issued_rfq
    _quote_and_accept(client, admin_headers, rfq, acme_supplier.id, {cement_id: "42"})
    assert _convert(client, admin_headers, rfq["id"], warehouse_1.id).status_code == 422  # sand not quoted
    assert db_session.query(PurchaseOrder).count() == 0
    ok = _convert(client, admin_headers, rfq["id"], warehouse_1.id, [{"rfq_line_id": cement_id, "unit_price": "40.25"}])
    assert ok.status_code == 200
    assert db_session.query(PurchaseOrderLine).one().unit_price == Decimal("40.2500")


def test_convert_requires_the_accepted_quotation_upload(client, admin_headers, issued_rfq, acme_supplier, warehouse_1, db_session):
    rfq, cement_id, _ = issued_rfq
    body = _capture(client, admin_headers, rfq["id"], _invitation_for(rfq, acme_supplier.id)["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}]).json()
    # A legacy selection made before uploads were required.
    record = db_session.query(Rfq).filter(Rfq.id == rfq["id"]).one()
    record.status = "selected"
    record.selected_response_id = _invitation_for(body, acme_supplier.id)["responses"][0]["id"]
    db_session.commit()
    assert _convert(client, admin_headers, rfq["id"], warehouse_1.id, [{"rfq_line_id": cement_id}]).status_code == 400


# --- cancel / list / isolation / permissions ------------------------------------------------


def test_cancel_requires_reason_and_status_endpoint_only_cancels(client, admin_headers, issued_rfq):
    rfq, _, _ = issued_rfq
    url = f"/api/rfqs/{rfq['id']}/status"
    assert client.patch(url, json={"status": "cancelled"}, headers=admin_headers).status_code == 422
    assert client.patch(url, json={"status": "issued"}, headers=admin_headers).status_code == 422
    cancelled = client.patch(url, json={"status": "cancelled", "cancel_reason": "Not needed"}, headers=admin_headers)
    assert cancelled.json()["status"] == "cancelled"


def test_list_filters_by_invited_supplier_and_priority(client, admin_headers, acme_supplier, beta_supplier, cement_raw_material):
    line = [_line(cement_raw_material)]
    urgent = _create(client, admin_headers, _form([acme_supplier.id], line, submit=False, priority="urgent")).json()
    normal = _create(client, admin_headers, _form([beta_supplier.id], line, submit=False)).json()
    by_supplier = client.get("/api/rfqs", params={"supplier_id": acme_supplier.id}, headers=admin_headers).json()
    assert [r["id"] for r in by_supplier["data"]] == [urgent["id"]]
    by_priority = client.get("/api/rfqs", params={"priority": "normal"}, headers=admin_headers).json()
    assert [r["id"] for r in by_priority["data"]] == [normal["id"]]


def test_other_organisation_sees_nothing(client, admin_headers, other_admin_headers, issued_rfq, acme_supplier):
    rfq, cement_id, _ = issued_rfq
    invitation = _invitation_for(rfq, acme_supplier.id)
    assert client.get(f"/api/rfqs/{rfq['id']}", headers=other_admin_headers).status_code == 404
    assert client.get("/api/rfqs", headers=other_admin_headers).json()["data"] == []
    assert client.get(f"/api/files/{invitation['pdf_file']['id']}", headers=other_admin_headers).status_code == 404
    assert _capture(client, other_admin_headers, rfq["id"], invitation["id"], [{"rfq_line_id": cement_id, "unit_price": "1"}]).status_code == 404
    assert client.post(f"/api/rfqs/{rfq['id']}/invitations/{invitation['id']}/send", headers=other_admin_headers).status_code == 404


def test_team_member_denied_by_default(client, active_user):
    assert client.get("/api/rfqs", headers=_login_headers(client)).status_code == 403
