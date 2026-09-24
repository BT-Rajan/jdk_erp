"""Tests for docs/modules/categories.md: organisation-scoped classification
master for Products/Raw Materials -- list/get (open read), admin-gated
create/edit/activate-deactivate, per-organisation name/code uniqueness,
and the audit trail for each mutation."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import CATEGORY_CREATED, CATEGORY_STATUS_CHANGED, CATEGORY_UPDATED, AuditEvent
from app.models.category import Category


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- list / get (open read) ------------------------------------------------


def test_categories_list_requires_authentication(client, active_user):
    response = client.get("/api/categories")
    assert response.status_code == 401


def test_list_categories_returns_only_my_organisation(
    client, active_user, electronics_category, other_organisation, db_session
):
    other_category = Category(applies_to="product", organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    db_session.add(other_category)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/categories", headers=headers)

    assert response.status_code == 200
    category_ids = {c["id"] for c in response.json()["data"]}
    assert category_ids == {electronics_category.id}


def test_get_category_in_other_organisation_returns_404(client, active_user, other_organisation, db_session):
    other_category = Category(applies_to="product", organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    db_session.add(other_category)
    db_session.commit()
    db_session.refresh(other_category)

    headers = _login_headers(client)
    response = client.get(f"/api/categories/{other_category.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_category_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/categories/999999", headers=headers)
    assert response.status_code == 404


def test_list_categories_excludes_inactive_by_default(client, active_user, organisation, db_session):
    inactive = Category(applies_to="product", organisation_id=organisation.id, name="Discontinued", code="DISC", is_active=False)
    db_session.add(inactive)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/categories", headers=headers)
    names = {c["name"] for c in response.json()["data"]}
    assert "Discontinued" not in names

    with_inactive = client.get("/api/categories?include_inactive=true", headers=headers)
    names_with_inactive = {c["name"] for c in with_inactive.json()["data"]}
    assert "Discontinued" in names_with_inactive


def test_list_categories_search_narrows_by_name_or_code(client, active_user, electronics_category, organisation, db_session):
    other = Category(applies_to="product", organisation_id=organisation.id, name="Hardware", code="HW", is_active=True)
    db_session.add(other)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/categories?q=elec", headers=headers)
    names = {c["name"] for c in response.json()["data"]}
    assert names == {"Electronics"}


# --- uniqueness (DB level) --------------------------------------------------


def test_category_name_unique_within_organisation_but_not_across(db_session, organisation, other_organisation):
    category_a = Category(applies_to="product", organisation_id=organisation.id, name="Electronics", code="ELEC1", is_active=True)
    db_session.add(category_a)
    db_session.commit()

    duplicate_in_same_org = Category(applies_to="product", organisation_id=organisation.id, name="Electronics", code="ELEC2", is_active=True)
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    same_name_other_org = Category(applies_to="product", organisation_id=other_organisation.id, name="Electronics", code="ELEC1", is_active=True)
    db_session.add(same_name_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


def test_category_code_unique_within_organisation_but_not_across(db_session, organisation, other_organisation):
    """code is now system-generated and required (docs/modules/categories.md
    #4) -- still DB-enforced unique per organisation, same as every
    other master's code."""
    category_a = Category(applies_to="product", organisation_id=organisation.id, name="Electronics", code="ELEC", is_active=True)
    db_session.add(category_a)
    db_session.commit()

    duplicate_code = Category(applies_to="product", organisation_id=organisation.id, name="Electronics Parts", code="ELEC", is_active=True)
    db_session.add(duplicate_code)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    same_code_other_org = Category(applies_to="product", organisation_id=other_organisation.id, name="Electronics", code="ELEC", is_active=True)
    db_session.add(same_code_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_category(client, active_user):
    headers = _login_headers(client)
    response = client.post("/api/categories", json={"applies_to": "product", "name": "Electronics"}, headers=headers)
    assert response.status_code == 403


def test_create_category_requires_authentication(client, admin_user):
    response = client.post("/api/categories", json={"applies_to": "product", "name": "Electronics"})
    assert response.status_code == 401


def test_admin_can_create_category(client, db_session, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/categories", json={"applies_to": "product", "name": "Electronics", "description": "Electronic parts"}, headers=headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Electronics"
    # code is system-generated: prefix "5" + a 5-digit per-organisation
    # sequence (docs/modules/categories.md #4) -- never caller-supplied.
    assert body["code"] == "500001"
    assert body["is_active"] is True
    assert body["organisation_id"] == admin_user.organisation_id

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == CATEGORY_CREATED, AuditEvent.entity_id == body["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert event.details == "name: Electronics"


def test_create_category_ignores_a_caller_supplied_code(client, admin_user):
    """`code` is never accepted from the request body -- sending one is
    silently ignored, not an error, since the schema simply has no such
    field to bind it to."""
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/categories", json={"applies_to": "product", "name": "Electronics", "code": "HACKED"}, headers=headers
    )
    assert response.status_code == 201
    assert response.json()["code"] == "500001"


def test_create_category_generates_sequential_codes(client, admin_user):
    headers = _login_headers(client, "admin_person")
    first = client.post("/api/categories", json={"applies_to": "product", "name": "Electronics"}, headers=headers)
    second = client.post("/api/categories", json={"applies_to": "product", "name": "Chemicals"}, headers=headers)
    assert first.json()["code"] == "500001"
    assert second.json()["code"] == "500002"


def test_create_category_rejects_blank_name(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/categories", json={"applies_to": "product", "name": "   "}, headers=headers)
    assert response.status_code == 422


def test_create_category_rejects_duplicate_name(client, admin_user, electronics_category):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/categories", json={"applies_to": "product", "name": electronics_category.name}, headers=headers)
    assert response.status_code == 409


def test_create_category_in_one_organisation_does_not_block_another(
    client, db_session, admin_user, electronics_category, other_organisation
):
    """Cross-org isolation on the write path, not just reads -- an admin
    in one organisation creating "Electronics" must never be blocked by
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
    response = client.post("/api/categories", json={"applies_to": "product", "name": "Electronics"}, headers=headers)
    assert response.status_code == 201


# --- update ------------------------------------------------------------


def test_non_admin_cannot_edit_category(client, active_user, electronics_category):
    headers = _login_headers(client)
    response = client.patch(f"/api/categories/{electronics_category.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_edit_category(client, db_session, admin_user, electronics_category):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/categories/{electronics_category.id}",
        json={"name": "Consumer Electronics", "description": "Updated"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Consumer Electronics"
    assert body["description"] == "Updated"
    # code was never sent -- a PATCH, not a full replace.
    assert body["code"] == electronics_category.code

    db_session.refresh(electronics_category)
    assert electronics_category.name == "Consumer Electronics"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == CATEGORY_UPDATED, AuditEvent.entity_id == electronics_category.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "name:" in event.details


def test_edit_category_rejects_blank_name(client, admin_user, electronics_category):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/categories/{electronics_category.id}", json={"name": "   "}, headers=headers)
    assert response.status_code == 422


def test_edit_category_rejects_a_name_already_used_by_another_category(
    client, db_session, admin_user, electronics_category, organisation
):
    other = Category(applies_to="product", organisation_id=organisation.id, name="Hardware", code="HW", is_active=True)
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/categories/{other.id}", json={"name": electronics_category.name}, headers=headers)
    assert response.status_code == 409

    db_session.refresh(other)
    assert other.name == "Hardware"


def test_edit_category_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    other_category = Category(applies_to="product", organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    db_session.add(other_category)
    db_session.commit()
    db_session.refresh(other_category)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/categories/{other_category.id}", json={"name": "Hijacked"}, headers=headers)
    assert response.status_code == 404


def test_edit_category_ignores_id_and_organisation_id_in_the_payload(
    client, db_session, admin_user, electronics_category, other_organisation
):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/categories/{electronics_category.id}",
        json={"id": 999999, "organisation_id": other_organisation.id, "name": "Still Mine"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == electronics_category.id

    db_session.refresh(electronics_category)
    assert electronics_category.name == "Still Mine"
    assert electronics_category.organisation_id != other_organisation.id


# --- activate / deactivate ----------------------------------------------


def test_non_admin_cannot_change_category_status(client, active_user, electronics_category):
    headers = _login_headers(client)
    response = client.patch(
        f"/api/categories/{electronics_category.id}/status", json={"is_active": False}, headers=headers
    )
    assert response.status_code == 403


def test_admin_can_deactivate_and_reactivate_category(client, db_session, admin_user, electronics_category):
    headers = _login_headers(client, "admin_person")

    deactivate = client.patch(
        f"/api/categories/{electronics_category.id}/status", json={"is_active": False}, headers=headers
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    db_session.refresh(electronics_category)
    assert electronics_category.is_active is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == CATEGORY_STATUS_CHANGED, AuditEvent.entity_id == electronics_category.id)
        .first()
    )
    assert event is not None
    assert event.actor_user_id == admin_user.id
    assert event.details == "is_active: False"

    reactivate = client.patch(
        f"/api/categories/{electronics_category.id}/status", json={"is_active": True}, headers=headers
    )
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


def test_deactivated_category_still_visible_with_include_inactive(client, admin_user, electronics_category):
    headers = _login_headers(client, "admin_person")
    client.patch(f"/api/categories/{electronics_category.id}/status", json={"is_active": False}, headers=headers)

    response = client.get(f"/api/categories/{electronics_category.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_category_type_is_required_and_filters_the_list(client, admin_user, electronics_category, raw_material_category):
    headers = _login_headers(client, "admin_person")
    assert client.post("/api/categories", json={"name": "Untyped"}, headers=headers).status_code == 422
    assert client.post("/api/categories", json={"name": "Bad", "applies_to": "service"}, headers=headers).status_code == 422

    products = client.get("/api/categories", params={"applies_to": "product"}, headers=headers).json()["data"]
    materials = client.get("/api/categories", params={"applies_to": "raw_material"}, headers=headers).json()["data"]
    assert [c["name"] for c in products] == ["Electronics"]
    assert [c["name"] for c in materials] == ["Building Materials"]


def test_products_and_raw_materials_only_take_their_own_category_type(
    client, admin_user, electronics_category, raw_material_category, kilogram_unit
):
    headers = _login_headers(client, "admin_person")
    product = {"name": "Panel", "category_id": raw_material_category.id, "unit_of_measure_id": kilogram_unit.id, "selling_price": "10"}
    refused = client.post("/api/products", json=product, headers=headers)
    assert refused.status_code == 422
    assert "category_id" in refused.json()["error"]["fields"]
    assert client.post("/api/products", json={**product, "category_id": electronics_category.id}, headers=headers).status_code == 201

    material = {"name": "Sand", "category_id": electronics_category.id, "unit_of_measure_id": kilogram_unit.id}
    assert client.post("/api/raw-materials", json=material, headers=headers).status_code == 422
    assert client.post("/api/raw-materials", json={**material, "category_id": raw_material_category.id}, headers=headers).status_code == 201


def test_category_type_cannot_change_once_used(client, admin_user, raw_material_category, cement_raw_material):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/categories/{raw_material_category.id}", json={"applies_to": "product"}, headers=headers)
    assert response.status_code == 400
    assert "applies_to" in response.json()["error"]["fields"]


def test_record_keeps_a_deactivated_category_when_edited(client, admin_user, raw_material_category, cement_raw_material):
    headers = _login_headers(client, "admin_person")
    client.patch(f"/api/categories/{raw_material_category.id}/status", json={"is_active": False}, headers=headers)
    # The edit form resends the unchanged category; that must still save.
    response = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}",
        json={"name": "Cement OPC", "category_id": raw_material_category.id},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Cement OPC"
