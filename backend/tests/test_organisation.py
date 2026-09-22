"""Tests for docs/modules/organisation.md acceptance criteria, including
the admin-gated edit/activate-deactivate API added once RBAC existed to
gate it (see docs/audit/ORGANISATION_AUDIT.md for jdk_clean's prior lack
of any organisation concept)."""

from app.models.audit_event import ORGANISATION_STATUS_CHANGED, ORGANISATION_UPDATED, AuditEvent


def test_deactivated_organisation_blocks_login(client, user_in_inactive_organisation):
    response = client.post(
        "/api/auth/login", json={"username": "suspended_org_user", "password": "Str0ng!Pass"}
    )
    assert response.status_code == 401
    # Same generic message as any other login failure -- an inactive
    # organisation isn't a channel for enumerating tenants either.
    assert response.json()["error"]["message"] == "Invalid username or password."


def test_deactivating_organisation_kills_an_already_issued_token(
    client, db_session, active_user, organisation
):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    access_token = login.json()["access_token"]

    still_valid = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert still_valid.status_code == 200

    organisation.is_active = False
    db_session.add(organisation)
    db_session.commit()

    now_blocked = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert now_blocked.status_code == 401


def test_deactivated_organisation_blocks_refresh(client, db_session, active_user, organisation):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    refresh_token = login.json()["refresh_token"]

    organisation.is_active = False
    db_session.add(organisation)
    db_session.commit()

    response = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401


def test_my_organisation_endpoint_requires_authentication(client, active_user):
    unauthenticated = client.get("/api/organisations/me")
    assert unauthenticated.status_code == 401


def test_my_organisation_endpoint_returns_own_organisation_only(client, active_user, organisation):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get("/api/organisations/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == organisation.id
    assert body["name"] == "Test Org"
    assert body["code"] == "TESTORG"
    assert body["currency"] == "USD"
    assert body["is_active"] is True


def test_organisation_code_must_be_unique(db_session, organisation):
    from app.models.organisation import Organisation

    duplicate = Organisation(name="Another Org", code=organisation.code, currency="USD", timezone="UTC")
    db_session.add(duplicate)

    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_organisation_name_must_be_unique(db_session, organisation):
    from app.models.organisation import Organisation

    duplicate = Organisation(name=organisation.name, code="DIFFERENT", currency="USD", timezone="UTC")
    db_session.add(duplicate)

    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_my_organisation_endpoint_never_returns_another_organisation(client, admin_user, other_organisation):
    """Explicit cross-org isolation guard for /me itself -- the endpoint's
    query shape (`filter(Organisation.id == current_user.organisation_id)`)
    already makes this structurally impossible, but this pins it down as
    a regression test rather than relying only on the shape being read
    correctly by a future editor."""
    login = client.post("/api/auth/login", json={"username": "admin_person", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.get("/api/organisations/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] != other_organisation.id


def test_admin_can_edit_organisation_details(client, db_session, admin_user, organisation):
    login = client.post("/api/auth/login", json={"username": "admin_person", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.patch(
        "/api/organisations/me",
        json={"name": "Renamed Org", "currency": "kwd", "timezone": "Asia/Kuwait", "contact_email": "Ops@Example.com"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed Org"
    assert body["currency"] == "KWD"
    assert body["timezone"] == "Asia/Kuwait"
    assert body["contact_email"] == "ops@example.com"
    # code/address were never sent -- a PATCH, not a full replace.
    assert body["code"] == organisation.code

    db_session.refresh(organisation)
    assert organisation.name == "Renamed Org"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == ORGANISATION_UPDATED, AuditEvent.entity_id == organisation.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "name:" in event.details


def test_non_admin_cannot_edit_organisation(client, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.patch("/api/organisations/me", json={"name": "Hijacked"}, headers=headers)
    assert response.status_code == 403


def test_editing_organisation_rejects_invalid_timezone(client, admin_user):
    login = client.post("/api/auth/login", json={"username": "admin_person", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.patch("/api/organisations/me", json={"timezone": "Not/A_Zone"}, headers=headers)
    assert response.status_code == 422


def test_editing_organisation_rejects_invalid_currency(client, admin_user):
    login = client.post("/api/auth/login", json={"username": "admin_person", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.patch("/api/organisations/me", json={"currency": "US"}, headers=headers)
    assert response.status_code == 422


def test_editing_organisation_rejects_a_code_already_used_by_another_organisation(
    client, db_session, admin_user, organisation, other_organisation
):
    login = client.post("/api/auth/login", json={"username": "admin_person", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.patch("/api/organisations/me", json={"code": other_organisation.code}, headers=headers)
    assert response.status_code == 409

    db_session.refresh(organisation)
    assert organisation.code != other_organisation.code


def test_editing_organisation_ignores_id_and_organisation_id_in_the_payload(
    client, db_session, admin_user, organisation, other_organisation
):
    """docs/modules/organisation.md #3 -- client-supplied identifiers must
    never determine which row is written. The schema doesn't declare
    `id`/`organisation_id` fields at all, so Pydantic silently drops
    them; this pins that down as the actual observed behaviour."""
    login = client.post("/api/auth/login", json={"username": "admin_person", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.patch(
        "/api/organisations/me",
        json={"id": other_organisation.id, "organisation_id": other_organisation.id, "name": "Still My Org"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == organisation.id

    db_session.refresh(organisation)
    assert organisation.name == "Still My Org"
    db_session.refresh(other_organisation)
    assert other_organisation.name != "Still My Org"


def test_admin_can_deactivate_own_organisation(client, db_session, admin_user, organisation):
    login = client.post("/api/auth/login", json={"username": "admin_person", "password": "Str0ng!Pass"})
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    response = client.patch("/api/organisations/me/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    db_session.refresh(organisation)
    assert organisation.is_active is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == ORGANISATION_STATUS_CHANGED, AuditEvent.entity_id == organisation.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id

    # The point of the feature: it locks out everyone, the acting admin
    # included, on the very next request -- same guarantee already
    # proven for a direct DB flip above, now proven for this endpoint too.
    now_blocked = client.get("/api/auth/me", headers=headers)
    assert now_blocked.status_code == 401

    login_attempt = client.post("/api/auth/login", json={"username": "admin_person", "password": "Str0ng!Pass"})
    assert login_attempt.status_code == 401


def test_non_admin_cannot_change_organisation_status(client, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    response = client.patch("/api/organisations/me/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 403
