"""Tests for docs/modules/suppliers.md: organisation-scoped vendor master
consumed by Procurement -- list/get (open read), admin-gated create/edit/
activate-deactivate, auto-generated code, per-organisation name/phone
uniqueness, and the audit trail for each mutation."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import SUPPLIER_CREATED, SUPPLIER_STATUS_CHANGED, SUPPLIER_UPDATED, AuditEvent
from app.models.supplier import Supplier


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- list / get (open read) ------------------------------------------------


def test_suppliers_list_requires_authentication(client, active_user):
    response = client.get("/api/suppliers")
    assert response.status_code == 401


def test_list_suppliers_returns_only_my_organisation(client, active_user, acme_supplier, other_organisation, db_session):
    other_supplier = Supplier(organisation_id=other_organisation.id, code="SUP0001", name="Acme Traders", is_active=True)
    db_session.add(other_supplier)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/suppliers", headers=headers)

    assert response.status_code == 200
    supplier_ids = {s["id"] for s in response.json()["data"]}
    assert supplier_ids == {acme_supplier.id}


def test_get_supplier_in_other_organisation_returns_404(client, active_user, other_organisation, db_session):
    other_supplier = Supplier(organisation_id=other_organisation.id, code="SUP0001", name="Acme Traders", is_active=True)
    db_session.add(other_supplier)
    db_session.commit()
    db_session.refresh(other_supplier)

    headers = _login_headers(client)
    response = client.get(f"/api/suppliers/{other_supplier.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_supplier_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/suppliers/999999", headers=headers)
    assert response.status_code == 404


def test_list_suppliers_excludes_inactive_by_default(client, active_user, organisation, db_session):
    inactive = Supplier(organisation_id=organisation.id, code="SUP0002", name="Discontinued Vendor", is_active=False)
    db_session.add(inactive)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/suppliers", headers=headers)
    names = {s["name"] for s in response.json()["data"]}
    assert "Discontinued Vendor" not in names

    with_inactive = client.get("/api/suppliers?include_inactive=true", headers=headers)
    names_with_inactive = {s["name"] for s in with_inactive.json()["data"]}
    assert "Discontinued Vendor" in names_with_inactive


def test_list_suppliers_search_narrows_by_name_or_code(client, active_user, acme_supplier, organisation, db_session):
    other = Supplier(organisation_id=organisation.id, code="SUP0002", name="Beta Chemicals", is_active=True)
    db_session.add(other)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/suppliers?q=acme", headers=headers)
    names = {s["name"] for s in response.json()["data"]}
    assert names == {"Acme Traders"}


# --- uniqueness (DB level) --------------------------------------------------


def test_supplier_name_unique_within_organisation_but_not_across(db_session, organisation, other_organisation):
    supplier_a = Supplier(organisation_id=organisation.id, code="SUP0001", name="Acme Traders", is_active=True)
    db_session.add(supplier_a)
    db_session.commit()

    duplicate_in_same_org = Supplier(organisation_id=organisation.id, code="SUP0002", name="Acme Traders", is_active=True)
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    same_name_other_org = Supplier(organisation_id=other_organisation.id, code="SUP0001", name="Acme Traders", is_active=True)
    db_session.add(same_name_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


def test_supplier_phone_unique_within_organisation_when_provided(db_session, organisation):
    supplier_a = Supplier(organisation_id=organisation.id, code="SUP0001", name="Acme Traders", phone="1234567890", is_active=True)
    db_session.add(supplier_a)
    db_session.commit()

    duplicate_phone = Supplier(
        organisation_id=organisation.id, code="SUP0002", name="Different Name", phone="1234567890", is_active=True
    )
    db_session.add(duplicate_phone)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Multiple suppliers with no phone at all must still be allowed.
    no_phone_a = Supplier(organisation_id=organisation.id, code="SUP0003", name="No Phone A", is_active=True)
    no_phone_b = Supplier(organisation_id=organisation.id, code="SUP0004", name="No Phone B", is_active=True)
    db_session.add_all([no_phone_a, no_phone_b])
    db_session.commit()  # must not raise


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_supplier(client, active_user):
    headers = _login_headers(client)
    response = client.post("/api/suppliers", json={"name": "Acme Traders"}, headers=headers)
    assert response.status_code == 403


def test_create_supplier_requires_authentication(client, admin_user):
    response = client.post("/api/suppliers", json={"name": "Acme Traders"})
    assert response.status_code == 401


def test_admin_can_create_supplier(client, db_session, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/suppliers",
        json={
            "name": "Acme Traders",
            "contact_person": "Jane Doe",
            "phone": "+965 1234 5678",
            "email": "jane@acme.example",
            "address": "Industrial Area, Plot 4",
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Traders"
    assert body["code"] == "SUP0001"
    assert body["phone"] == "96512345678"  # digits-only normalization
    assert body["is_active"] is True
    assert body["organisation_id"] == admin_user.organisation_id

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == SUPPLIER_CREATED, AuditEvent.entity_id == body["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "Acme Traders" in event.details


def test_create_supplier_generates_sequential_codes(client, admin_user):
    headers = _login_headers(client, "admin_person")
    first = client.post("/api/suppliers", json={"name": "Vendor One"}, headers=headers)
    second = client.post("/api/suppliers", json={"name": "Vendor Two"}, headers=headers)
    assert first.json()["code"] == "SUP0001"
    assert second.json()["code"] == "SUP0002"


def test_create_supplier_normalizes_phone_to_digits_only(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/suppliers", json={"name": "Acme Traders", "phone": "+965-1234-5678"}, headers=headers)
    assert response.status_code == 201
    assert response.json()["phone"] == "96512345678"


def test_create_supplier_rejects_blank_name(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/suppliers", json={"name": "   "}, headers=headers)
    assert response.status_code == 422


def test_create_supplier_rejects_duplicate_name(client, admin_user, acme_supplier):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/suppliers", json={"name": acme_supplier.name}, headers=headers)
    assert response.status_code == 409


def test_create_supplier_rejects_duplicate_phone(client, admin_user, db_session, organisation):
    existing = Supplier(organisation_id=organisation.id, code="SUP0009", name="Existing Vendor", phone="19876543210", is_active=True)
    db_session.add(existing)
    db_session.commit()

    headers = _login_headers(client, "admin_person")
    response = client.post("/api/suppliers", json={"name": "New Vendor", "phone": "1 987 654 3210"}, headers=headers)
    assert response.status_code == 409


def test_create_supplier_in_one_organisation_does_not_block_another(
    client, db_session, admin_user, acme_supplier, other_organisation
):
    """Cross-org isolation on the write path, not just reads -- an admin
    in one organisation creating "Acme Traders" must never be blocked by
    another organisation already having that name."""
    from app.core.security import hash_password
    from app.core.roles import ADMIN
    from app.models.user import User

    other_admin = User(
        organisation_id=other_organisation.id,
        role=ADMIN,
        full_name="Other Org Admin",
        email="other_admin@example.com",
        username="other_admin",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(other_admin)
    db_session.commit()

    headers = _login_headers(client, "other_admin")
    response = client.post("/api/suppliers", json={"name": "Acme Traders"}, headers=headers)
    assert response.status_code == 201


# --- update ------------------------------------------------------------


def test_non_admin_cannot_edit_supplier(client, active_user, acme_supplier):
    headers = _login_headers(client)
    response = client.patch(f"/api/suppliers/{acme_supplier.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_edit_supplier(client, db_session, admin_user, acme_supplier):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/suppliers/{acme_supplier.id}",
        json={"name": "Acme Trading Co", "contact_person": "New Contact"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Acme Trading Co"
    assert body["contact_person"] == "New Contact"
    # code was never sent -- a PATCH, not a full replace.
    assert body["code"] == acme_supplier.code

    db_session.refresh(acme_supplier)
    assert acme_supplier.name == "Acme Trading Co"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == SUPPLIER_UPDATED, AuditEvent.entity_id == acme_supplier.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "name:" in event.details


def test_edit_supplier_rejects_blank_name(client, admin_user, acme_supplier):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/suppliers/{acme_supplier.id}", json={"name": "   "}, headers=headers)
    assert response.status_code == 422


def test_edit_supplier_rejects_a_name_already_used_by_another_supplier(
    client, db_session, admin_user, acme_supplier, organisation
):
    other = Supplier(organisation_id=organisation.id, code="SUP0002", name="Beta Chemicals", is_active=True)
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/suppliers/{other.id}", json={"name": acme_supplier.name}, headers=headers)
    assert response.status_code == 409

    db_session.refresh(other)
    assert other.name == "Beta Chemicals"


def test_edit_supplier_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    other_supplier = Supplier(organisation_id=other_organisation.id, code="SUP0001", name="Acme Traders", is_active=True)
    db_session.add(other_supplier)
    db_session.commit()
    db_session.refresh(other_supplier)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/suppliers/{other_supplier.id}", json={"name": "Hijacked"}, headers=headers)
    assert response.status_code == 404


def test_edit_supplier_ignores_id_and_organisation_id_in_the_payload(
    client, db_session, admin_user, acme_supplier, other_organisation
):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/suppliers/{acme_supplier.id}",
        json={"id": 999999, "organisation_id": other_organisation.id, "name": "Still Mine"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == acme_supplier.id

    db_session.refresh(acme_supplier)
    assert acme_supplier.name == "Still Mine"
    assert acme_supplier.organisation_id != other_organisation.id


# --- activate / deactivate ----------------------------------------------


def test_non_admin_cannot_change_supplier_status(client, active_user, acme_supplier):
    headers = _login_headers(client)
    response = client.patch(f"/api/suppliers/{acme_supplier.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 403


def test_admin_can_deactivate_and_reactivate_supplier(client, db_session, admin_user, acme_supplier):
    headers = _login_headers(client, "admin_person")

    deactivate = client.patch(f"/api/suppliers/{acme_supplier.id}/status", json={"is_active": False}, headers=headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    db_session.refresh(acme_supplier)
    assert acme_supplier.is_active is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == SUPPLIER_STATUS_CHANGED, AuditEvent.entity_id == acme_supplier.id)
        .first()
    )
    assert event is not None
    assert event.actor_user_id == admin_user.id
    assert event.details == "is_active: False"

    reactivate = client.patch(f"/api/suppliers/{acme_supplier.id}/status", json={"is_active": True}, headers=headers)
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


def test_deactivated_supplier_still_visible_with_include_inactive(client, admin_user, acme_supplier):
    headers = _login_headers(client, "admin_person")
    client.patch(f"/api/suppliers/{acme_supplier.id}/status", json={"is_active": False}, headers=headers)

    response = client.get(f"/api/suppliers/{acme_supplier.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False
