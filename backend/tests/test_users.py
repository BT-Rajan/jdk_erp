"""Tests for docs/modules/users.md acceptance criteria implemented at this
stage: the organisation-scoped directory (criterion 13), user creation
(criteria 1/5/6/12) and activate/deactivate (criterion 7), plus locking in
the documented global-uniqueness decision so it can't drift silently."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models.user import User
from app.models.user_team import UserTeam


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_users_list_requires_authentication(client, active_user):
    response = client.get("/api/users")
    assert response.status_code == 401


def test_list_users_returns_only_my_organisation(client, active_user, other_org_user):
    headers = _login_headers(client)
    response = client.get("/api/users", headers=headers)

    assert response.status_code == 200
    usernames = {u["username"] for u in response.json()}
    assert usernames == {"ada"}
    assert "grace" not in usernames


def test_list_users_excludes_password_hash(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/users", headers=headers)

    for user in response.json():
        assert "password_hash" not in user
        assert "password" not in user


def test_list_users_excludes_inactive_by_default(client, active_user, inactive_user):
    headers = _login_headers(client)
    response = client.get("/api/users", headers=headers)

    usernames = {u["username"] for u in response.json()}
    assert usernames == {"ada"}

    include_inactive = client.get("/api/users?include_inactive=true", headers=headers)
    usernames_with_inactive = {u["username"] for u in include_inactive.json()}
    assert usernames_with_inactive == {"ada", "inactive_user"}


def test_get_user_in_own_organisation(client, active_user):
    headers = _login_headers(client)
    response = client.get(f"/api/users/{active_user.id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["username"] == "ada"


def test_get_user_in_other_organisation_returns_404(client, active_user, other_org_user):
    headers = _login_headers(client)
    response = client.get(f"/api/users/{other_org_user.id}", headers=headers)

    assert response.status_code == 404


def test_get_nonexistent_user_also_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/users/999999", headers=headers)
    assert response.status_code == 404


def test_username_is_unique_globally_across_organisations(db_session, active_user, other_organisation):
    """Locks in the documented decision (docs/modules/users.md) to keep
    login-identifier uniqueness global rather than per-organisation, since
    login has no organisation selector today."""
    duplicate = User(
        organisation_id=other_organisation.id,
        full_name="Someone Else",
        email="someone-else@example.com",
        username="ada",  # same username as active_user, different org
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_email_is_unique_globally_across_organisations(db_session, active_user, other_organisation):
    duplicate = User(
        organisation_id=other_organisation.id,
        full_name="Someone Else",
        email="ada@example.com",  # same email as active_user, different org
        username="someone_else",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()


# --- POST /api/users (docs/modules/users.md #4/#10) -------------------------


def _create_payload(**overrides):
    payload = {
        "full_name": "New Hire",
        "email": "new.hire@example.com",
        "username": "new_hire",
        "password": "Str0ng!Pass",
        "role": "team_member",
    }
    payload.update(overrides)
    return payload


def test_non_admin_cannot_create_user(client, active_user):
    headers = _login_headers(client)
    response = client.post("/api/users", json=_create_payload(), headers=headers)
    assert response.status_code == 403


def test_create_user_requires_authentication(client):
    response = client.post("/api/users", json=_create_payload())
    assert response.status_code == 401


def test_admin_can_create_user(client, admin_user, db_session):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/users", json=_create_payload(), headers=headers)

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "new_hire"
    assert body["organisation_id"] == admin_user.organisation_id
    assert "password" not in body and "password_hash" not in body

    created = db_session.query(User).filter_by(username="new_hire").first()
    assert created is not None
    assert created.is_active is True

    # The new user can actually log in with the password the admin set.
    login = client.post("/api/auth/login", json={"username": "new_hire", "password": "Str0ng!Pass"})
    assert login.status_code == 200


def test_create_user_assigns_teams(client, admin_user, sales_team, db_session):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/users", json=_create_payload(team_ids=[sales_team.id]), headers=headers)

    assert response.status_code == 201
    assert response.json()["team_ids"] == [sales_team.id]

    created = db_session.query(User).filter_by(username="new_hire").first()
    membership = db_session.query(UserTeam).filter_by(user_id=created.id, team_id=sales_team.id).first()
    assert membership is not None


def test_create_user_rejects_duplicate_username(client, admin_user, active_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/users", json=_create_payload(username="ada"), headers=headers)
    assert response.status_code == 409


def test_create_user_rejects_duplicate_email(client, admin_user, active_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/users", json=_create_payload(email="ada@example.com"), headers=headers)
    assert response.status_code == 409


def test_create_user_rejects_weak_password(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/users", json=_create_payload(password="weak"), headers=headers)
    assert response.status_code == 422


def test_create_user_rejects_invalid_role(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/users", json=_create_payload(role="superhero"), headers=headers)
    assert response.status_code == 422


def test_create_user_rejects_team_from_other_organisation(client, admin_user, other_organisation, db_session):
    from app.models.team import Team

    other_team = Team(organisation_id=other_organisation.id, name="Sales", is_active=True)
    db_session.add(other_team)
    db_session.commit()
    db_session.refresh(other_team)

    headers = _login_headers(client, "admin_person")
    response = client.post("/api/users", json=_create_payload(team_ids=[other_team.id]), headers=headers)
    assert response.status_code == 422


def test_create_user_rejects_nonexistent_team(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/users", json=_create_payload(team_ids=[999999]), headers=headers)
    assert response.status_code == 422


def test_create_user_enforces_company_email_domain(client, admin_user, organisation, db_session):
    organisation.email_domain = "example.com"
    db_session.add(organisation)
    db_session.commit()

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/users", json=_create_payload(email="new.hire@other-domain.com"), headers=headers
    )
    assert response.status_code == 422


# --- PATCH /api/users/{id}/status (docs/modules/users.md #6/#10 criterion 7) -


def test_non_admin_cannot_change_status(client, active_user):
    headers = _login_headers(client)
    response = client.patch(f"/api/users/{active_user.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 403


def test_admin_can_deactivate_a_user(client, admin_user, active_user, db_session):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/users/{active_user.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 204

    db_session.refresh(active_user)
    assert active_user.is_active is False

    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    assert login.status_code == 401


def test_admin_can_reactivate_a_user(client, admin_user, inactive_user, db_session):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/users/{inactive_user.id}/status", json={"is_active": True}, headers=headers)
    assert response.status_code == 204

    db_session.refresh(inactive_user)
    assert inactive_user.is_active is True


def test_admin_cannot_deactivate_own_account(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/users/{admin_user.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 400


def test_admin_cannot_change_status_of_user_in_other_organisation(client, admin_user, other_org_user):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/users/{other_org_user.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 404
