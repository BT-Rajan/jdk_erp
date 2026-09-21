"""Tests for docs/modules/users.md acceptance criteria implemented at this
stage: the organisation-scoped directory (criterion 13), plus locking in
the documented global-uniqueness decision so it can't drift silently."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models.user import User


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
