"""Tests for the behaviour required by docs/modules/authentication.md and
the fixes tracked in docs/audit/AUTHENTICATION_AUDIT.md."""


def test_login_success_returns_tokens_and_records_last_login(client, active_user, db_session):
    response = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})

    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"

    db_session.refresh(active_user)
    assert active_user.last_login_at is not None


def test_login_wrong_password_is_rejected(client, active_user):
    response = client.post("/api/auth/login", json={"username": "ada", "password": "wrong-password"})
    assert response.status_code == 401
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "AUTHENTICATION_ERROR"
    assert body["error"]["message"] == "Invalid username or password."
    assert "request_id" in body


def test_login_unknown_user_gets_identical_message_to_wrong_password(client, active_user):
    """No enumeration channel: a nonexistent username must look identical
    to a real username with a wrong password (AUTHENTICATION_AUDIT.md #4)."""
    wrong_password = client.post("/api/auth/login", json={"username": "ada", "password": "wrong-password"})
    unknown_user = client.post("/api/auth/login", json={"username": "nobody", "password": "whatever123!"})

    assert unknown_user.status_code == wrong_password.status_code == 401
    assert unknown_user.json()["error"]["message"] == wrong_password.json()["error"]["message"]


def test_login_inactive_user_gets_generic_message(client, inactive_user):
    """A deactivated account with the correct password must not get a
    message that reveals the account exists (AUTHENTICATION_AUDIT.md #3)."""
    response = client.post("/api/auth/login", json={"username": "inactive_user", "password": "Str0ng!Pass"})
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Invalid username or password."


def test_login_locks_out_after_repeated_failures(client, active_user):
    # LOGIN_LOCKOUT_THRESHOLD=3 in tests/conftest.py
    for _ in range(3):
        response = client.post("/api/auth/login", json={"username": "ada", "password": "wrong-password"})
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Invalid username or password."

    # Even the *correct* password is now rejected until the window passes.
    # RATE_LIMITED/429, not AUTHENTICATION_ERROR/401 -- this is a rate
    # limit, not a credentials failure (docs/modules/api_error_handling.md #6).
    locked = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "RATE_LIMITED"
    assert locked.json()["error"]["message"] == "Too many failed login attempts. Please try again later."


def test_refresh_rotates_and_rejects_replay(client, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    old_refresh_token = login.json()["refresh_token"]

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": old_refresh_token})
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != old_refresh_token

    replay = client.post("/api/auth/refresh", json={"refresh_token": old_refresh_token})
    assert replay.status_code == 401


def test_refresh_rejects_an_access_token(client, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    access_token = login.json()["access_token"]

    response = client.post("/api/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


def test_logout_revokes_the_refresh_token(client, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    refresh_token = login.json()["refresh_token"]

    logout = client.post("/api/auth/logout", json={"refresh_token": refresh_token})
    assert logout.status_code == 204

    reuse = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse.status_code == 401


def test_me_requires_authentication(client, active_user):
    unauthenticated = client.get("/api/auth/me")
    assert unauthenticated.status_code == 401

    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    access_token = login.json()["access_token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "ada"
    assert "password_hash" not in body
    assert "password" not in body


def test_change_password_requires_current_password(client, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    access_token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    wrong_current = client.post(
        "/api/auth/change-password",
        json={"current_password": "not-the-password", "new_password": "NewStr0ng!Pass"},
        headers=headers,
    )
    assert wrong_current.status_code == 422
    body = wrong_current.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["fields"]["current_password"] == "Current password is incorrect."


def test_change_password_rejects_weak_new_passwords(client, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    for weak_password in ["short1!", "nouppercase1!", "NoDigitsHere!", "NoSpecialChar1"]:
        response = client.post(
            "/api/auth/change-password",
            json={"current_password": "Str0ng!Pass", "new_password": weak_password},
            headers=headers,
        )
        assert response.status_code == 422, weak_password


def test_change_password_succeeds_and_revokes_existing_sessions(client, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    old_refresh_token = login.json()["refresh_token"]
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    change = client.post(
        "/api/auth/change-password",
        json={"current_password": "Str0ng!Pass", "new_password": "NewStr0ng!Pass1"},
        headers=headers,
    )
    assert change.status_code == 204

    # The old session is dead...
    reuse = client.post("/api/auth/refresh", json={"refresh_token": old_refresh_token})
    assert reuse.status_code == 401

    # ...but the new password logs in fine.
    relogin = client.post("/api/auth/login", json={"username": "ada", "password": "NewStr0ng!Pass1"})
    assert relogin.status_code == 200

    # And the old password no longer works.
    old_password = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    assert old_password.status_code == 401
