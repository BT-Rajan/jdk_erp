"""Tests for docs/modules/session_security.md: idle timeout, security
headers, and the new audit trail for role/team-membership changes.
Everything else the spec asks for (rate limiting, generic invalid-
credential messages, password-change revoking sessions, parameterized
queries) is already covered by test_auth.py -- see
docs/audit/SESSION_SECURITY_AUDIT.md's section-by-section table."""
from datetime import datetime, timedelta

from app.models.audit_event import LOGIN_SUCCESS, LOGOUT, ROLE_CHANGED, TEAM_ADDED, TEAM_REMOVED, AuditEvent
from app.models.refresh_token import RefreshToken
from app.models.team import Team
from app.models.user_team import UserTeam


def _headers(client, username, password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- idle timeout --------------------------------------------------------


def test_refresh_succeeds_within_idle_window(client, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    refresh_token = login.json()["refresh_token"]

    response = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200


def test_refresh_fails_after_idle_timeout(client, active_user, db_session):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    refresh_token = login.json()["refresh_token"]

    # Simulate a session that hasn't been used in a very long time,
    # without needing to wait or change global test configuration.
    record = db_session.query(RefreshToken).filter(RefreshToken.user_id == active_user.id).first()
    record.last_used_at = datetime.utcnow() - timedelta(days=365)
    db_session.add(record)
    db_session.commit()

    response = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401
    assert "inactivity" in response.json()["error"]["message"].lower()


def test_refresh_updates_last_used_at_on_success(client, active_user, db_session):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    refresh_token = login.json()["refresh_token"]

    original = db_session.query(RefreshToken).filter(RefreshToken.user_id == active_user.id).first()
    original_created_at = original.created_at

    refreshed = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert refreshed.status_code == 200

    new_record = (
        db_session.query(RefreshToken)
        .filter(RefreshToken.user_id == active_user.id, RefreshToken.revoked.is_(False))
        .first()
    )
    assert new_record.last_used_at >= original_created_at


# --- security headers ----------------------------------------------------


def test_security_headers_present_on_every_response(client):
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "content-security-policy" in response.headers


def test_hsts_not_set_when_https_not_forced(client):
    response = client.get("/health")
    assert "strict-transport-security" not in response.headers


# --- role change: session revocation + audit trail ------------------------


def test_role_change_revokes_existing_sessions(client, admin_user, active_user):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    refresh_token = login.json()["refresh_token"]

    admin_headers = _headers(client, "admin_person")
    role_change = client.patch(f"/api/users/{active_user.id}/role", json={"role": "manager"}, headers=admin_headers)
    assert role_change.status_code == 204

    reuse = client.post("/api/auth/refresh", json={"refresh_token": refresh_token})
    assert reuse.status_code == 401


def test_role_change_is_logged_with_actor(client, admin_user, active_user, db_session):
    admin_headers = _headers(client, "admin_person")
    client.patch(f"/api/users/{active_user.id}/role", json={"role": "manager"}, headers=admin_headers)

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == ROLE_CHANGED, AuditEvent.user_id == active_user.id)
        .first()
    )
    assert event is not None
    assert event.actor_user_id == admin_user.id
    assert event.entity_type == "user"
    assert event.entity_id == active_user.id
    assert event.details == "role: team_member -> manager"


# --- team membership audit trail ------------------------------------------


def test_team_membership_changes_are_logged_with_actor(client, admin_user, active_user, organisation, db_session):
    team = Team(organisation_id=organisation.id, name="Sales", is_active=True)
    db_session.add(team)
    db_session.commit()
    db_session.refresh(team)

    admin_headers = _headers(client, "admin_person")
    add_response = client.post(f"/api/teams/{team.id}/members", json={"user_id": active_user.id}, headers=admin_headers)
    assert add_response.status_code == 204

    added_event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == TEAM_ADDED, AuditEvent.user_id == active_user.id)
        .first()
    )
    assert added_event is not None
    assert added_event.actor_user_id == admin_user.id
    assert added_event.entity_type == "user"
    assert added_event.entity_id == active_user.id
    assert added_event.details == f"team: {team.name} (id={team.id})"

    remove_response = client.delete(f"/api/teams/{team.id}/members/{active_user.id}", headers=admin_headers)
    assert remove_response.status_code == 204

    removed_event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == TEAM_REMOVED, AuditEvent.user_id == active_user.id)
        .first()
    )
    assert removed_event is not None
    assert removed_event.actor_user_id == admin_user.id


def test_login_and_logout_record_actor(client, active_user, db_session):
    login = client.post("/api/auth/login", json={"username": "ada", "password": "Str0ng!Pass"})
    refresh_token = login.json()["refresh_token"]

    login_event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == LOGIN_SUCCESS, AuditEvent.user_id == active_user.id)
        .order_by(AuditEvent.id.desc())
        .first()
    )
    assert login_event.actor_user_id == active_user.id

    client.post("/api/auth/logout", json={"refresh_token": refresh_token})
    logout_event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == LOGOUT, AuditEvent.user_id == active_user.id)
        .first()
    )
    assert logout_event.actor_user_id == active_user.id
