"""Tests for docs/modules/audit_trail.md: the audit_service helpers
(diff_fields/format_changes/log_event) and the GET /api/audit-events
read API (admin-gated, organisation-scoped, filterable, paginated).
Security-event coverage (login/logout/role/team writes) is exercised in
test_session_security.py; this file focuses on what's new here: the
generalized table and its read side."""
from app.core.roles import TEAM_MEMBER
from app.core.security import hash_password
from app.models.audit_event import AuditEvent
from app.models.user import User
from app.services import audit_service


def _headers(client, username, password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- audit_service helpers ------------------------------------------------


def test_diff_fields_returns_only_changed_fields():
    before = {"name": "Sales", "code": "SALES", "is_active": True}
    after = {"name": "Sales EMEA", "code": "SALES", "is_active": True}

    changes = audit_service.diff_fields(before, after)

    assert changes == {"name": ("Sales", "Sales EMEA")}


def test_diff_fields_respects_ignored_fields():
    before = {"name": "Sales", "updated_at": "yesterday"}
    after = {"name": "Sales", "updated_at": "today"}

    changes = audit_service.diff_fields(before, after, ignored_fields=frozenset({"updated_at"}))

    assert changes == {}


def test_format_changes_renders_readable_lines():
    changes = {"role": ("team_member", "manager"), "team": ("Sales", "Accounts")}

    rendered = audit_service.format_changes(changes)

    assert rendered == "role: team_member -> manager; team: Sales -> Accounts"


def test_log_event_does_not_commit(db_session, organisation):
    """docs/modules/audit_trail.md #12: the caller commits the audit
    event together with the business change, not log_event itself."""
    audit_service.log_event(
        db_session, action="created", module="sales", organisation_id=organisation.id, entity_type="quotation",
        entity_id=1,
    )
    db_session.rollback()

    assert db_session.query(AuditEvent).filter(AuditEvent.action == "created").first() is None


# --- GET /api/audit-events --------------------------------------------


def test_audit_events_requires_authentication(client):
    response = client.get("/api/audit-events")
    assert response.status_code == 401


def test_non_admin_cannot_list_audit_events(client, active_user):
    headers = _headers(client, "ada")
    response = client.get("/api/audit-events", headers=headers)
    assert response.status_code == 403


def test_admin_can_list_audit_events(client, admin_user, active_user):
    headers = _headers(client, "admin_person")
    response = client.get("/api/audit-events", headers=headers)
    assert response.status_code == 200
    actions = {e["action"] for e in response.json()}
    # The admin's own login and ada's fixture creation don't themselves
    # generate a login event, but logging in as admin here does.
    assert "login_success" in actions


def test_audit_events_scoped_to_own_organisation(client, admin_user, other_organisation, db_session):
    other_user = User(
        organisation_id=other_organisation.id,
        full_name="Other Org Person",
        email="other-org-person@example.com",
        username="other_org_person",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
        role=TEAM_MEMBER,
    )
    db_session.add(other_user)
    db_session.commit()

    # Generate an audit event in the other organisation.
    client.post("/api/auth/login", json={"username": "other_org_person", "password": "Str0ng!Pass"})

    headers = _headers(client, "admin_person")
    response = client.get("/api/audit-events", headers=headers)

    usernames = {e["username_attempted"] for e in response.json()}
    assert "other_org_person" not in usernames


def test_audit_events_filters_by_action(client, admin_user, active_user):
    headers = _headers(client, "admin_person")

    response = client.get("/api/audit-events?action=login_success", headers=headers)
    assert response.status_code == 200
    assert all(e["action"] == "login_success" for e in response.json())


def test_audit_events_filters_by_module(client, admin_user, organisation, db_session):
    audit_service.log_event(
        db_session, action="approved", module="sales", organisation_id=organisation.id, actor_user_id=admin_user.id,
        entity_type="quotation", entity_id=1024, result="success",
    )
    db_session.commit()

    headers = _headers(client, "admin_person")
    response = client.get("/api/audit-events?module=sales", headers=headers)
    assert response.status_code == 200
    events = response.json()
    assert len(events) == 1
    assert events[0]["action"] == "approved"
    assert events[0]["entity_type"] == "quotation"
    assert events[0]["entity_id"] == 1024


def test_audit_events_pagination(client, admin_user, organisation, db_session):
    for i in range(5):
        audit_service.log_event(
            db_session, action="created", module="sales", organisation_id=organisation.id,
            actor_user_id=admin_user.id, entity_type="quotation", entity_id=i,
        )
    db_session.commit()

    headers = _headers(client, "admin_person")
    page = client.get("/api/audit-events?module=sales&limit=2", headers=headers)
    assert len(page.json()) == 2


def test_audit_events_excludes_events_with_no_resolvable_organisation(client, admin_user, db_session):
    """An unknown-username login failure has no organisation to
    attribute -- docs/modules/audit_trail.md #7 -- so it must never
    appear in any organisation's admin's listing."""
    client.post("/api/auth/login", json={"username": "totally_unknown_user", "password": "whatever123!"})

    headers = _headers(client, "admin_person")
    response = client.get("/api/audit-events", headers=headers)
    usernames = {e["username_attempted"] for e in response.json()}
    assert "totally_unknown_user" not in usernames
