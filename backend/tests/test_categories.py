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
    other_category = Category(organisation_id=other_organisation.id, name="Electronics", is_active=True)
    db_session.add(other_category)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/categories", headers=headers)

    assert response.status_code == 200
    category_ids = {c["id"] for c in response.json()["data"]}
    assert category_ids == {electronics_category.id}


def test_get_category_in_other_organisation_returns_404(client, active_user, other_organisation, db_session):
    other_category = Category(organisation_id=other_organisation.id, name="Electronics", is_active=True)
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
    inactive = Category(organisation_id=organisation.id, name="Discontinued", is_active=False)
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
    other = Category(organisation_id=organisation.id, name="Hardware", code="HW", is_active=True)
    db_session.add(other)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/categories?q=elec", headers=headers)
    names = {c["name"] for c in response.json()["data"]}
    assert names == {"Electronics"}


# --- uniqueness (DB level) --------------------------------------------------


def test_category_name_unique_within_organisation_but_not_across(db_session, organisation, other_organisation):
    category_a = Category(organisation_id=organisation.id, name="Electronics", is_active=True)
    db_session.add(category_a)
    db_session.commit()

    duplicate_in_same_org = Category(organisation_id=organisation.id, name="Electronics", is_active=True)
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    same_name_other_org = Category(organisation_id=other_organisation.id, name="Electronics", is_active=True)
    db_session.add(same_name_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


def test_category_code_unique_within_organisation_when_provided(db_session, organisation):
    category_a = Category(organisation_id=organisation.id, name="Electronics", code="ELEC", is_active=True)
    db_session.add(category_a)
    db_session.commit()

    duplicate_code = Category(organisation_id=organisation.id, name="Electronics Parts", code="ELEC", is_active=True)
    db_session.add(duplicate_code)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Multiple categories with no code at all must still be allowed.
    no_code_a = Category(organisation_id=organisation.id, name="No Code A", is_active=True)
    no_code_b = Category(organisation_id=organisation.id, name="No Code B", is_active=True)
    db_session.add_all([no_code_a, no_code_b])
    db_session.commit()  # must not raise


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_category(client, active_user):
    headers = _login_headers(client)
    response = client.post("/api/categories", json={"name": "Electronics"}, headers=headers)
    assert response.status_code == 403


def test_create_category_requires_authentication(client, admin_user):
    response = client.post("/api/categories", json={"name": "Electronics"})
    assert response.status_code == 401


def test_admin_can_create_category(client, db_session, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/categories", json={"name": "Electronics", "code": "ELEC", "description": "Electronic parts"}, headers=headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Electronics"
    assert body["code"] == "ELEC"
    assert body["is_active"] is True
    assert body["organisation_id"] == admin_user.organisation_id

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == CATEGORY_CREATED, AuditEvent.entity_id == body["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert event.details == "name: Electronics"


def test_create_category_rejects_blank_name(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/categories", json={"name": "   "}, headers=headers)
    assert response.status_code == 422


def test_create_category_rejects_duplicate_name(client, admin_user, electronics_category):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/categories", json={"name": electronics_category.name}, headers=headers)
    assert response.status_code == 409


def test_create_category_rejects_duplicate_code(client, admin_user, electronics_category):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/categories", json={"name": "Something Else", "code": electronics_category.code}, headers=headers
    )
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
    response = client.post("/api/categories", json={"name": "Electronics"}, headers=headers)
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
    other = Category(organisation_id=organisation.id, name="Hardware", is_active=True)
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/categories/{other.id}", json={"name": electronics_category.name}, headers=headers)
    assert response.status_code == 409

    db_session.refresh(other)
    assert other.name == "Hardware"


def test_edit_category_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    other_category = Category(organisation_id=other_organisation.id, name="Electronics", is_active=True)
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
