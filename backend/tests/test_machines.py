"""Tests for docs/modules/machines.md: organisation-scoped Machine
master -- list/get (open read), admin-gated create/edit/activate-
deactivate, required active ProductionLine/UnitOfMeasure FK validation,
per-organisation code/name uniqueness, immutable code, structured
capacity (quantity/unit/period, all positive), reconfiguring capacity
without a code change, and the audit trail for each mutation."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import MACHINE_CREATED, MACHINE_STATUS_CHANGED, MACHINE_UPDATED, AuditEvent
from app.models.machine import Machine


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- list / get (open read) ------------------------------------------------


def test_machines_list_requires_authentication(client, active_user):
    response = client.get("/api/machines")
    assert response.status_code == 401


def test_list_machines_returns_only_my_organisation(client, active_user, machine_1, other_organisation, db_session):
    from app.models.production_line import ProductionLine
    from app.models.unit import UnitOfMeasure

    other_line = ProductionLine(organisation_id=other_organisation.id, code="LINE1", name="Line 1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_line, other_unit])
    db_session.commit()
    other_machine = Machine(
        organisation_id=other_organisation.id,
        code="M-001",
        name="Machine 1",
        production_line_id=other_line.id,
        capacity_quantity=2,
        capacity_unit_of_measure_id=other_unit.id,
        capacity_period_hours=1,
        is_active=True,
    )
    db_session.add(other_machine)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/machines", headers=headers)

    assert response.status_code == 200
    machine_ids = {m["id"] for m in response.json()["data"]}
    assert machine_ids == {machine_1.id}


def test_get_machine_in_other_organisation_returns_404(client, active_user, other_organisation, db_session):
    from app.models.production_line import ProductionLine
    from app.models.unit import UnitOfMeasure

    other_line = ProductionLine(organisation_id=other_organisation.id, code="LINE1", name="Line 1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_line, other_unit])
    db_session.commit()
    other_machine = Machine(
        organisation_id=other_organisation.id,
        code="M-001",
        name="Machine 1",
        production_line_id=other_line.id,
        capacity_quantity=2,
        capacity_unit_of_measure_id=other_unit.id,
        capacity_period_hours=1,
        is_active=True,
    )
    db_session.add(other_machine)
    db_session.commit()
    db_session.refresh(other_machine)

    headers = _login_headers(client)
    response = client.get(f"/api/machines/{other_machine.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_machine_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/machines/999999", headers=headers)
    assert response.status_code == 404


def test_list_machines_excludes_inactive_by_default(client, active_user, organisation, line_1, kilogram_unit, db_session):
    inactive = Machine(
        organisation_id=organisation.id,
        code="M-999",
        name="Retired Machine",
        production_line_id=line_1.id,
        capacity_quantity=1,
        capacity_unit_of_measure_id=kilogram_unit.id,
        capacity_period_hours=1,
        is_active=False,
    )
    db_session.add(inactive)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/machines", headers=headers)
    names = {m["name"] for m in response.json()["data"]}
    assert "Retired Machine" not in names

    with_inactive = client.get("/api/machines?include_inactive=true", headers=headers)
    names_with_inactive = {m["name"] for m in with_inactive.json()["data"]}
    assert "Retired Machine" in names_with_inactive


# --- uniqueness (DB level) --------------------------------------------------


def test_machine_code_unique_within_organisation_but_not_across(
    db_session, organisation, other_organisation, line_1, kilogram_unit
):
    from app.models.production_line import ProductionLine
    from app.models.unit import UnitOfMeasure

    machine_a = Machine(
        organisation_id=organisation.id,
        code="M-001",
        name="Machine A",
        production_line_id=line_1.id,
        capacity_quantity=2,
        capacity_unit_of_measure_id=kilogram_unit.id,
        capacity_period_hours=1,
        is_active=True,
    )
    db_session.add(machine_a)
    db_session.commit()

    duplicate_in_same_org = Machine(
        organisation_id=organisation.id,
        code="M-001",
        name="Machine B",
        production_line_id=line_1.id,
        capacity_quantity=1,
        capacity_unit_of_measure_id=kilogram_unit.id,
        capacity_period_hours=1,
        is_active=True,
    )
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    other_line = ProductionLine(organisation_id=other_organisation.id, code="LINE1", name="Line 1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_line, other_unit])
    db_session.commit()
    same_code_other_org = Machine(
        organisation_id=other_organisation.id,
        code="M-001",
        name="Machine A",
        production_line_id=other_line.id,
        capacity_quantity=2,
        capacity_unit_of_measure_id=other_unit.id,
        capacity_period_hours=1,
        is_active=True,
    )
    db_session.add(same_code_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_machine(client, active_user, line_1, kilogram_unit):
    headers = _login_headers(client)
    response = client.post(
        "/api/machines",
        json={
            "name": "Machine 1",
            "production_line_id": line_1.id,
            "capacity_quantity": "2",
            "capacity_unit_of_measure_id": kilogram_unit.id,
            "capacity_period_hours": "1",
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_admin_can_create_machine_with_configured_capacity(client, db_session, admin_user, line_1, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/machines",
        json={
            "name": "Machine 1",
            "production_line_id": line_1.id,
            "capacity_quantity": "2",
            "capacity_unit_of_measure_id": kilogram_unit.id,
            "capacity_period_hours": "1",
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    # code is system-generated: "00002" + a single per-organisation
    # sequence digit (per explicit user instruction) -- never
    # caller-supplied.
    assert body["code"] == "000021"
    assert body["production_line_id"] == line_1.id
    assert body["capacity_quantity"] == "2.0000"
    assert body["capacity_unit_of_measure_id"] == kilogram_unit.id
    assert body["capacity_period_hours"] == "1.00"
    assert body["is_active"] is True

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == MACHINE_CREATED, AuditEvent.entity_id == body["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_create_machine_rejects_zero_capacity(client, admin_user, line_1, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/machines",
        json={
            "name": "Machine 1",
            "production_line_id": line_1.id,
            "capacity_quantity": "0",
            "capacity_unit_of_measure_id": kilogram_unit.id,
            "capacity_period_hours": "1",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_machine_rejects_negative_period(client, admin_user, line_1, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/machines",
        json={
            "name": "Machine 1",
            "production_line_id": line_1.id,
            "capacity_quantity": "2",
            "capacity_unit_of_measure_id": kilogram_unit.id,
            "capacity_period_hours": "-1",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_machine_rejects_inactive_production_line(client, admin_user, db_session, organisation, kilogram_unit):
    from app.models.production_line import ProductionLine

    inactive_line = ProductionLine(organisation_id=organisation.id, code="LINE2", name="Old Line", is_active=False)
    db_session.add(inactive_line)
    db_session.commit()
    db_session.refresh(inactive_line)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/machines",
        json={
            "name": "Machine 1",
            "production_line_id": inactive_line.id,
            "capacity_quantity": "2",
            "capacity_unit_of_measure_id": kilogram_unit.id,
            "capacity_period_hours": "1",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_machine_rejects_cross_organisation_production_line(
    client, admin_user, other_organisation, kilogram_unit, db_session
):
    from app.models.production_line import ProductionLine

    other_line = ProductionLine(organisation_id=other_organisation.id, code="LINE1", name="Line 1", is_active=True)
    db_session.add(other_line)
    db_session.commit()
    db_session.refresh(other_line)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/machines",
        json={
            "name": "Machine 1",
            "production_line_id": other_line.id,
            "capacity_quantity": "2",
            "capacity_unit_of_measure_id": kilogram_unit.id,
            "capacity_period_hours": "1",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_machine_rejects_inactive_unit(client, admin_user, line_1, db_session, organisation):
    from app.models.unit import UnitOfMeasure

    inactive_unit = UnitOfMeasure(organisation_id=organisation.id, name="Ton", code="TON", is_active=False)
    db_session.add(inactive_unit)
    db_session.commit()
    db_session.refresh(inactive_unit)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/machines",
        json={
            "name": "Machine 1",
            "production_line_id": line_1.id,
            "capacity_quantity": "2",
            "capacity_unit_of_measure_id": inactive_unit.id,
            "capacity_period_hours": "1",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_machine_ignores_a_caller_supplied_code(client, admin_user, line_1, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/machines",
        json={
            "code": "HACKED",
            "name": "Machine 1",
            "production_line_id": line_1.id,
            "capacity_quantity": "1",
            "capacity_unit_of_measure_id": kilogram_unit.id,
            "capacity_period_hours": "1",
        },
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["code"] == "000021"


def test_create_machine_rejects_an_eleventh_machine(client, admin_user, db_session, organisation, line_1, kilogram_unit):
    """MACHINE_CODE's single free digit caps this master at 9 records
    (docs/modules/machines.md) -- a real business limit, surfaced as a
    clear 400 rather than an unhandled error."""
    from app.models.machine import Machine

    for i in range(1, 10):
        db_session.add(
            Machine(
                organisation_id=organisation.id,
                code=f"00002{i}",
                name=f"Machine {i}",
                production_line_id=line_1.id,
                capacity_quantity=1,
                capacity_unit_of_measure_id=kilogram_unit.id,
                capacity_period_hours=1,
                is_active=True,
            )
        )
    db_session.commit()

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/machines",
        json={
            "name": "One Too Many",
            "production_line_id": line_1.id,
            "capacity_quantity": "1",
            "capacity_unit_of_measure_id": kilogram_unit.id,
            "capacity_period_hours": "1",
        },
        headers=headers,
    )
    assert response.status_code == 400


# --- update (reconfiguring capacity without a code change) -------------


def test_non_admin_cannot_edit_machine(client, active_user, machine_1):
    headers = _login_headers(client)
    response = client.patch(f"/api/machines/{machine_1.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_reconfigure_capacity(client, db_session, admin_user, machine_1):
    """docs/modules/machines.md #4: an authorised user can change 2 -> 2.5
    tonnes/hour without any code change."""
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/machines/{machine_1.id}", json={"capacity_quantity": "2.5"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["capacity_quantity"] == "2.5000"
    # code was never sent -- a PATCH, not a full replace, and code has no
    # update path at all.
    assert response.json()["code"] == machine_1.code

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == MACHINE_UPDATED, AuditEvent.entity_id == machine_1.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "capacity_quantity" in event.details


def test_edit_machine_code_is_not_accepted(client, admin_user, machine_1):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/machines/{machine_1.id}", json={"code": "CHANGED", "name": "Still Machine 1"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["code"] == machine_1.code


def test_edit_machine_rejects_zero_capacity(client, admin_user, machine_1):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/machines/{machine_1.id}", json={"capacity_quantity": "0"}, headers=headers)
    assert response.status_code == 422


def test_edit_machine_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    from app.models.production_line import ProductionLine
    from app.models.unit import UnitOfMeasure

    other_line = ProductionLine(organisation_id=other_organisation.id, code="LINE1", name="Line 1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_line, other_unit])
    db_session.commit()
    other_machine = Machine(
        organisation_id=other_organisation.id,
        code="M-001",
        name="Machine 1",
        production_line_id=other_line.id,
        capacity_quantity=2,
        capacity_unit_of_measure_id=other_unit.id,
        capacity_period_hours=1,
        is_active=True,
    )
    db_session.add(other_machine)
    db_session.commit()
    db_session.refresh(other_machine)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/machines/{other_machine.id}", json={"name": "Hijacked"}, headers=headers)
    assert response.status_code == 404


# --- activate / deactivate ----------------------------------------------


def test_non_admin_cannot_change_machine_status(client, active_user, machine_1):
    headers = _login_headers(client)
    response = client.patch(f"/api/machines/{machine_1.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 403


def test_admin_can_deactivate_and_reactivate_machine(client, db_session, admin_user, machine_1):
    headers = _login_headers(client, "admin_person")

    deactivate = client.patch(f"/api/machines/{machine_1.id}/status", json={"is_active": False}, headers=headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == MACHINE_STATUS_CHANGED, AuditEvent.entity_id == machine_1.id)
        .first()
    )
    assert event is not None
    assert event.actor_user_id == admin_user.id

    reactivate = client.patch(f"/api/machines/{machine_1.id}/status", json={"is_active": True}, headers=headers)
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


def test_deactivated_machine_still_visible_with_include_inactive(client, admin_user, machine_1):
    headers = _login_headers(client, "admin_person")
    client.patch(f"/api/machines/{machine_1.id}/status", json={"is_active": False}, headers=headers)

    response = client.get(f"/api/machines/{machine_1.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False
