"""Tests for docs/modules/machines.md: organisation-scoped Production
Line master -- list/get (open read), admin-gated create/edit/activate-
deactivate, per-organisation code/name uniqueness, immutable code, and
the audit trail for each mutation. Mirrors test_categories.py's coverage
shape -- ProductionLine follows the same admin-gated CRUD pattern."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import (
    PRODUCTION_LINE_CREATED,
    PRODUCTION_LINE_STATUS_CHANGED,
    PRODUCTION_LINE_UPDATED,
    AuditEvent,
)
from app.models.production_line import ProductionLine


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- list / get (open read) ------------------------------------------------


def test_production_lines_list_requires_authentication(client, active_user):
    response = client.get("/api/production-lines")
    assert response.status_code == 401


def test_list_production_lines_returns_only_my_organisation(client, active_user, line_1, other_organisation, db_session):
    other_line = ProductionLine(organisation_id=other_organisation.id, code="LINE1", name="Production Line 1", is_active=True)
    db_session.add(other_line)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/production-lines", headers=headers)

    assert response.status_code == 200
    line_ids = {line["id"] for line in response.json()["data"]}
    assert line_ids == {line_1.id}


def test_get_production_line_in_other_organisation_returns_404(client, active_user, other_organisation, db_session):
    other_line = ProductionLine(organisation_id=other_organisation.id, code="LINE1", name="Production Line 1", is_active=True)
    db_session.add(other_line)
    db_session.commit()
    db_session.refresh(other_line)

    headers = _login_headers(client)
    response = client.get(f"/api/production-lines/{other_line.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_production_line_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/production-lines/999999", headers=headers)
    assert response.status_code == 404


def test_list_production_lines_excludes_inactive_by_default(client, active_user, organisation, db_session):
    inactive = ProductionLine(organisation_id=organisation.id, code="LINE2", name="Decommissioned Line", is_active=False)
    db_session.add(inactive)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/production-lines", headers=headers)
    names = {line["name"] for line in response.json()["data"]}
    assert "Decommissioned Line" not in names

    with_inactive = client.get("/api/production-lines?include_inactive=true", headers=headers)
    names_with_inactive = {line["name"] for line in with_inactive.json()["data"]}
    assert "Decommissioned Line" in names_with_inactive


# --- uniqueness (DB level) --------------------------------------------------


def test_production_line_code_unique_within_organisation_but_not_across(db_session, organisation, other_organisation):
    line_a = ProductionLine(organisation_id=organisation.id, code="LINE1", name="Line A", is_active=True)
    db_session.add(line_a)
    db_session.commit()

    duplicate_in_same_org = ProductionLine(organisation_id=organisation.id, code="LINE1", name="Line B", is_active=True)
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    same_code_other_org = ProductionLine(organisation_id=other_organisation.id, code="LINE1", name="Line A", is_active=True)
    db_session.add(same_code_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_production_line(client, active_user):
    headers = _login_headers(client)
    response = client.post("/api/production-lines", json={"name": "Line 1"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_create_production_line(client, db_session, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/production-lines", json={"name": "Production Line 1"}, headers=headers)
    assert response.status_code == 201
    body = response.json()
    # code is system-generated: "00001" + a single per-organisation
    # sequence digit (per explicit user instruction) -- never
    # caller-supplied.
    assert body["code"] == "000011"
    assert body["name"] == "Production Line 1"
    assert body["is_active"] is True

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PRODUCTION_LINE_CREATED, AuditEvent.entity_id == body["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_create_production_line_ignores_a_caller_supplied_code(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/production-lines", json={"code": "HACKED", "name": "Line 1"}, headers=headers)
    assert response.status_code == 201
    assert response.json()["code"] == "000011"


def test_create_production_line_rejects_blank_name(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/production-lines", json={"name": "   "}, headers=headers)
    assert response.status_code == 422


def test_create_production_line_rejects_a_tenth_line(client, admin_user, db_session, organisation):
    """PRODUCTION_LINE_CODE's single free digit caps this master at 9
    records (docs/modules/production_lines.md) -- a real business limit,
    surfaced as a clear 400 rather than an unhandled error."""
    from app.models.production_line import ProductionLine

    for i in range(1, 10):
        db_session.add(ProductionLine(organisation_id=organisation.id, code=f"00001{i}", name=f"Line {i}", is_active=True))
    db_session.commit()

    headers = _login_headers(client, "admin_person")
    response = client.post("/api/production-lines", json={"name": "One Too Many"}, headers=headers)
    assert response.status_code == 400


# --- update ------------------------------------------------------------


def test_non_admin_cannot_edit_production_line(client, active_user, line_1):
    headers = _login_headers(client)
    response = client.patch(f"/api/production-lines/{line_1.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_edit_production_line(client, db_session, admin_user, line_1):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/production-lines/{line_1.id}", json={"name": "Main Line"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Main Line"
    assert response.json()["code"] == line_1.code

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PRODUCTION_LINE_UPDATED, AuditEvent.entity_id == line_1.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_edit_production_line_code_is_not_accepted(client, admin_user, line_1):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/production-lines/{line_1.id}", json={"code": "CHANGED", "name": "Still Line 1"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["code"] == line_1.code


# --- activate / deactivate ----------------------------------------------


def test_non_admin_cannot_change_production_line_status(client, active_user, line_1):
    headers = _login_headers(client)
    response = client.patch(f"/api/production-lines/{line_1.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 403


def test_admin_can_deactivate_and_reactivate_production_line(client, db_session, admin_user, line_1):
    headers = _login_headers(client, "admin_person")

    deactivate = client.patch(f"/api/production-lines/{line_1.id}/status", json={"is_active": False}, headers=headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PRODUCTION_LINE_STATUS_CHANGED, AuditEvent.entity_id == line_1.id)
        .first()
    )
    assert event is not None

    reactivate = client.patch(f"/api/production-lines/{line_1.id}/status", json={"is_active": True}, headers=headers)
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True
