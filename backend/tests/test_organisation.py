"""Tests for docs/modules/organisation.md acceptance criteria that are
implemented at this stage (see docs/audit/ORGANISATION_AUDIT.md for what's
deliberately deferred to RBAC)."""


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
