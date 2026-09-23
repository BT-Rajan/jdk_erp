"""Tests for docs/modules/warehouses.md: organisation-scoped Warehouse
master -- list/get (open read), admin-gated create/edit/activate-
deactivate, required active UnitOfMeasure FK validation, per-organisation
code/name uniqueness, immutable code, structured storage capacity
(positive area + unit), reconfiguring capacity without a code change,
and the audit trail for each mutation. Mirrors test_machines.py's
coverage shape."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import WAREHOUSE_CREATED, WAREHOUSE_STATUS_CHANGED, WAREHOUSE_UPDATED, AuditEvent
from app.models.warehouse import Warehouse


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- list / get (open read) ------------------------------------------------


def test_warehouses_list_requires_authentication(client, active_user):
    response = client.get("/api/warehouses")
    assert response.status_code == 401


def test_list_warehouses_returns_only_my_organisation(client, active_user, warehouse_1, other_organisation, db_session):
    from app.models.unit import UnitOfMeasure

    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    other_warehouse = Warehouse(
        organisation_id=other_organisation.id,
        code="WH-001",
        name="Factory Warehouse",
        total_usable_storage_area=5000,
        storage_area_unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(other_warehouse)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/warehouses", headers=headers)

    assert response.status_code == 200
    warehouse_ids = {w["id"] for w in response.json()["data"]}
    assert warehouse_ids == {warehouse_1.id}


def test_get_warehouse_in_other_organisation_returns_404(client, active_user, other_organisation, db_session):
    from app.models.unit import UnitOfMeasure

    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    other_warehouse = Warehouse(
        organisation_id=other_organisation.id,
        code="WH-001",
        name="Factory Warehouse",
        total_usable_storage_area=5000,
        storage_area_unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(other_warehouse)
    db_session.commit()
    db_session.refresh(other_warehouse)

    headers = _login_headers(client)
    response = client.get(f"/api/warehouses/{other_warehouse.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_warehouse_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/warehouses/999999", headers=headers)
    assert response.status_code == 404


def test_list_warehouses_excludes_inactive_by_default(client, active_user, organisation, kilogram_unit, db_session):
    inactive = Warehouse(
        organisation_id=organisation.id,
        code="WH-999",
        name="Decommissioned Warehouse",
        total_usable_storage_area=100,
        storage_area_unit_of_measure_id=kilogram_unit.id,
        is_active=False,
    )
    db_session.add(inactive)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/warehouses", headers=headers)
    names = {w["name"] for w in response.json()["data"]}
    assert "Decommissioned Warehouse" not in names

    with_inactive = client.get("/api/warehouses?include_inactive=true", headers=headers)
    names_with_inactive = {w["name"] for w in with_inactive.json()["data"]}
    assert "Decommissioned Warehouse" in names_with_inactive


# --- uniqueness (DB level) --------------------------------------------------


def test_warehouse_code_unique_within_organisation_but_not_across(
    db_session, organisation, other_organisation, kilogram_unit
):
    from app.models.unit import UnitOfMeasure

    warehouse_a = Warehouse(
        organisation_id=organisation.id,
        code="WH-001",
        name="Warehouse A",
        total_usable_storage_area=5000,
        storage_area_unit_of_measure_id=kilogram_unit.id,
        is_active=True,
    )
    db_session.add(warehouse_a)
    db_session.commit()

    duplicate_in_same_org = Warehouse(
        organisation_id=organisation.id,
        code="WH-001",
        name="Warehouse B",
        total_usable_storage_area=1000,
        storage_area_unit_of_measure_id=kilogram_unit.id,
        is_active=True,
    )
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    same_code_other_org = Warehouse(
        organisation_id=other_organisation.id,
        code="WH-001",
        name="Warehouse A",
        total_usable_storage_area=5000,
        storage_area_unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(same_code_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_warehouse(client, active_user, kilogram_unit):
    headers = _login_headers(client)
    response = client.post(
        "/api/warehouses",
        json={
            "code": "WH-001",
            "name": "Factory Warehouse",
            "total_usable_storage_area": "5000",
            "storage_area_unit_of_measure_id": kilogram_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_admin_can_create_warehouse_with_configured_capacity(client, db_session, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/warehouses",
        json={
            "code": "WH-001",
            "name": "Factory Warehouse",
            "total_usable_storage_area": "5000",
            "storage_area_unit_of_measure_id": kilogram_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "WH-001"
    assert body["total_usable_storage_area"] == "5000.00"
    assert body["storage_area_unit_of_measure_id"] == kilogram_unit.id
    assert body["is_active"] is True

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == WAREHOUSE_CREATED, AuditEvent.entity_id == body["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_create_warehouse_rejects_zero_area(client, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/warehouses",
        json={
            "code": "WH-001",
            "name": "Factory Warehouse",
            "total_usable_storage_area": "0",
            "storage_area_unit_of_measure_id": kilogram_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_warehouse_rejects_negative_area(client, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/warehouses",
        json={
            "code": "WH-001",
            "name": "Factory Warehouse",
            "total_usable_storage_area": "-100",
            "storage_area_unit_of_measure_id": kilogram_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_warehouse_rejects_inactive_unit(client, admin_user, db_session, organisation):
    from app.models.unit import UnitOfMeasure

    inactive_unit = UnitOfMeasure(organisation_id=organisation.id, name="Ton", code="TON", is_active=False)
    db_session.add(inactive_unit)
    db_session.commit()
    db_session.refresh(inactive_unit)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/warehouses",
        json={
            "code": "WH-001",
            "name": "Factory Warehouse",
            "total_usable_storage_area": "5000",
            "storage_area_unit_of_measure_id": inactive_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_warehouse_rejects_cross_organisation_unit(client, admin_user, other_organisation, db_session):
    from app.models.unit import UnitOfMeasure

    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    db_session.refresh(other_unit)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/warehouses",
        json={
            "code": "WH-001",
            "name": "Factory Warehouse",
            "total_usable_storage_area": "5000",
            "storage_area_unit_of_measure_id": other_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_warehouse_rejects_duplicate_code(client, admin_user, warehouse_1, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/warehouses",
        json={
            "code": warehouse_1.code,
            "name": "Another Warehouse",
            "total_usable_storage_area": "100",
            "storage_area_unit_of_measure_id": kilogram_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 409


# --- update (reconfiguring capacity without a code change) -------------


def test_non_admin_cannot_edit_warehouse(client, active_user, warehouse_1):
    headers = _login_headers(client)
    response = client.patch(f"/api/warehouses/{warehouse_1.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_reconfigure_storage_capacity(client, db_session, admin_user, warehouse_1):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/warehouses/{warehouse_1.id}", json={"total_usable_storage_area": "6000"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["total_usable_storage_area"] == "6000.00"
    # code was never sent -- a PATCH, not a full replace, and code has no
    # update path at all.
    assert response.json()["code"] == warehouse_1.code

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == WAREHOUSE_UPDATED, AuditEvent.entity_id == warehouse_1.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "total_usable_storage_area" in event.details


def test_edit_warehouse_code_is_not_accepted(client, admin_user, warehouse_1):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/warehouses/{warehouse_1.id}", json={"code": "CHANGED", "name": "Still Factory Warehouse"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["code"] == warehouse_1.code


def test_edit_warehouse_rejects_zero_area(client, admin_user, warehouse_1):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/warehouses/{warehouse_1.id}", json={"total_usable_storage_area": "0"}, headers=headers)
    assert response.status_code == 422


def test_edit_warehouse_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    from app.models.unit import UnitOfMeasure

    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    other_warehouse = Warehouse(
        organisation_id=other_organisation.id,
        code="WH-001",
        name="Factory Warehouse",
        total_usable_storage_area=5000,
        storage_area_unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(other_warehouse)
    db_session.commit()
    db_session.refresh(other_warehouse)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/warehouses/{other_warehouse.id}", json={"name": "Hijacked"}, headers=headers)
    assert response.status_code == 404


# --- activate / deactivate ----------------------------------------------


def test_non_admin_cannot_change_warehouse_status(client, active_user, warehouse_1):
    headers = _login_headers(client)
    response = client.patch(f"/api/warehouses/{warehouse_1.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 403


def test_admin_can_deactivate_and_reactivate_warehouse(client, db_session, admin_user, warehouse_1):
    headers = _login_headers(client, "admin_person")

    deactivate = client.patch(f"/api/warehouses/{warehouse_1.id}/status", json={"is_active": False}, headers=headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == WAREHOUSE_STATUS_CHANGED, AuditEvent.entity_id == warehouse_1.id)
        .first()
    )
    assert event is not None
    assert event.actor_user_id == admin_user.id

    reactivate = client.patch(f"/api/warehouses/{warehouse_1.id}/status", json={"is_active": True}, headers=headers)
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


def test_deactivated_warehouse_still_visible_with_include_inactive(client, admin_user, warehouse_1):
    headers = _login_headers(client, "admin_person")
    client.patch(f"/api/warehouses/{warehouse_1.id}/status", json={"is_active": False}, headers=headers)

    response = client.get(f"/api/warehouses/{warehouse_1.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False
