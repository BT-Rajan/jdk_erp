"""Tests for docs/modules/units_of_measure.md: organisation-scoped unit
master -- list/get (open read), admin-gated create/edit/activate-
deactivate, per-organisation name/code uniqueness with code normalized
to upper-case (docs/audit/UNITS_OF_MEASURE_AUDIT.md's "kg"/"Kg"/"KGS"
drift), and the audit trail for each mutation."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import UNIT_CREATED, UNIT_STATUS_CHANGED, UNIT_UPDATED, AuditEvent
from app.models.unit import UnitOfMeasure


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- list / get (open read) ------------------------------------------------


def test_units_list_requires_authentication(client, active_user):
    response = client.get("/api/units-of-measure")
    assert response.status_code == 401


def test_list_units_returns_only_my_organisation(client, active_user, kilogram_unit, other_organisation, db_session):
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/units-of-measure", headers=headers)

    assert response.status_code == 200
    unit_ids = {u["id"] for u in response.json()["data"]}
    assert unit_ids == {kilogram_unit.id}


def test_get_unit_in_other_organisation_returns_404(client, active_user, other_organisation, db_session):
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    db_session.refresh(other_unit)

    headers = _login_headers(client)
    response = client.get(f"/api/units-of-measure/{other_unit.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_unit_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/units-of-measure/999999", headers=headers)
    assert response.status_code == 404


def test_list_units_excludes_inactive_by_default(client, active_user, organisation, db_session):
    inactive = UnitOfMeasure(organisation_id=organisation.id, name="Fathom", code="FTH", is_active=False)
    db_session.add(inactive)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/units-of-measure", headers=headers)
    names = {u["name"] for u in response.json()["data"]}
    assert "Fathom" not in names

    with_inactive = client.get("/api/units-of-measure?include_inactive=true", headers=headers)
    names_with_inactive = {u["name"] for u in with_inactive.json()["data"]}
    assert "Fathom" in names_with_inactive


def test_list_units_search_narrows_by_name_or_code(client, active_user, kilogram_unit, organisation, db_session):
    other = UnitOfMeasure(organisation_id=organisation.id, name="Litre", code="L", is_active=True)
    db_session.add(other)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/units-of-measure?q=kilo", headers=headers)
    names = {u["name"] for u in response.json()["data"]}
    assert names == {"Kilogram"}


# --- uniqueness (DB level) --------------------------------------------------


def test_unit_name_unique_within_organisation_but_not_across(db_session, organisation, other_organisation):
    unit_a = UnitOfMeasure(organisation_id=organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(unit_a)
    db_session.commit()

    duplicate_in_same_org = UnitOfMeasure(organisation_id=organisation.id, name="Kilogram", code="KG2", is_active=True)
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    same_name_other_org = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(same_name_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


def test_unit_code_unique_within_organisation(db_session, organisation):
    unit_a = UnitOfMeasure(organisation_id=organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(unit_a)
    db_session.commit()

    duplicate_code = UnitOfMeasure(organisation_id=organisation.id, name="Kilogramme", code="KG", is_active=True)
    db_session.add(duplicate_code)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_unit(client, active_user):
    headers = _login_headers(client)
    response = client.post("/api/units-of-measure", json={"name": "Kilogram", "code": "kg"}, headers=headers)
    assert response.status_code == 403


def test_create_unit_requires_authentication(client, admin_user):
    response = client.post("/api/units-of-measure", json={"name": "Kilogram", "code": "kg"})
    assert response.status_code == 401


def test_admin_can_create_unit(client, db_session, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/units-of-measure",
        json={"name": "Kilogram", "code": "kg", "description": "Base weight unit"},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Kilogram"
    # Code is normalized to upper-case (docs/audit/UNITS_OF_MEASURE_AUDIT.md).
    assert body["code"] == "KG"
    assert body["is_active"] is True
    assert body["organisation_id"] == admin_user.organisation_id

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == UNIT_CREATED, AuditEvent.entity_id == body["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert event.details == "name: Kilogram (KG)"


def test_create_unit_rejects_blank_name(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/units-of-measure", json={"name": "   ", "code": "KG"}, headers=headers)
    assert response.status_code == 422


def test_create_unit_rejects_blank_code(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/units-of-measure", json={"name": "Kilogram", "code": "   "}, headers=headers)
    assert response.status_code == 422


def test_create_unit_requires_code(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = client.post("/api/units-of-measure", json={"name": "Kilogram"}, headers=headers)
    assert response.status_code == 422


def test_create_unit_rejects_duplicate_name(client, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/units-of-measure", json={"name": kilogram_unit.name, "code": "KG2"}, headers=headers
    )
    assert response.status_code == 409


def test_create_unit_rejects_duplicate_code_case_insensitively(client, admin_user, kilogram_unit):
    """kilogram_unit's code is "KG" -- sending lowercase "kg" must still
    collide, since code is normalized before the uniqueness check runs."""
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/units-of-measure", json={"name": "Kilogramme", "code": "kg"}, headers=headers
    )
    assert response.status_code == 409


def test_create_unit_in_one_organisation_does_not_block_another(
    client, db_session, admin_user, kilogram_unit, other_organisation
):
    from app.core.security import hash_password
    from app.core.roles import ADMIN
    from app.models.user import User

    other_admin = User(
        organisation_id=other_organisation.id,
        role=ADMIN,
        full_name="Other Org Admin",
        email="other_admin@example.com",
        username="other_admin",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(other_admin)
    db_session.commit()

    headers = _login_headers(client, "other_admin")
    response = client.post("/api/units-of-measure", json={"name": "Kilogram", "code": "KG"}, headers=headers)
    assert response.status_code == 201


# --- update ------------------------------------------------------------


def test_non_admin_cannot_edit_unit(client, active_user, kilogram_unit):
    headers = _login_headers(client)
    response = client.patch(f"/api/units-of-measure/{kilogram_unit.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_edit_unit(client, db_session, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/units-of-measure/{kilogram_unit.id}",
        json={"name": "Kilogramme", "description": "Updated"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Kilogramme"
    assert body["description"] == "Updated"
    # code was never sent -- a PATCH, not a full replace.
    assert body["code"] == kilogram_unit.code

    db_session.refresh(kilogram_unit)
    assert kilogram_unit.name == "Kilogramme"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == UNIT_UPDATED, AuditEvent.entity_id == kilogram_unit.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "name:" in event.details


def test_edit_unit_normalizes_code_to_upper_case(client, db_session, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/units-of-measure/{kilogram_unit.id}", json={"code": "kilo"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["code"] == "KILO"


def test_edit_unit_rejects_blank_name(client, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/units-of-measure/{kilogram_unit.id}", json={"name": "   "}, headers=headers)
    assert response.status_code == 422


def test_edit_unit_rejects_a_name_already_used_by_another_unit(
    client, db_session, admin_user, kilogram_unit, organisation
):
    other = UnitOfMeasure(organisation_id=organisation.id, name="Litre", code="L", is_active=True)
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/units-of-measure/{other.id}", json={"name": kilogram_unit.name}, headers=headers
    )
    assert response.status_code == 409

    db_session.refresh(other)
    assert other.name == "Litre"


def test_edit_unit_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    db_session.refresh(other_unit)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/units-of-measure/{other_unit.id}", json={"name": "Hijacked"}, headers=headers)
    assert response.status_code == 404


def test_edit_unit_ignores_id_and_organisation_id_in_the_payload(
    client, db_session, admin_user, kilogram_unit, other_organisation
):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/units-of-measure/{kilogram_unit.id}",
        json={"id": 999999, "organisation_id": other_organisation.id, "name": "Still Mine"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == kilogram_unit.id

    db_session.refresh(kilogram_unit)
    assert kilogram_unit.name == "Still Mine"
    assert kilogram_unit.organisation_id != other_organisation.id


# --- activate / deactivate ----------------------------------------------


def test_non_admin_cannot_change_unit_status(client, active_user, kilogram_unit):
    headers = _login_headers(client)
    response = client.patch(
        f"/api/units-of-measure/{kilogram_unit.id}/status", json={"is_active": False}, headers=headers
    )
    assert response.status_code == 403


def test_admin_can_deactivate_and_reactivate_unit(client, db_session, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")

    deactivate = client.patch(
        f"/api/units-of-measure/{kilogram_unit.id}/status", json={"is_active": False}, headers=headers
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    db_session.refresh(kilogram_unit)
    assert kilogram_unit.is_active is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == UNIT_STATUS_CHANGED, AuditEvent.entity_id == kilogram_unit.id)
        .first()
    )
    assert event is not None
    assert event.actor_user_id == admin_user.id
    assert event.details == "is_active: False"

    reactivate = client.patch(
        f"/api/units-of-measure/{kilogram_unit.id}/status", json={"is_active": True}, headers=headers
    )
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


def test_deactivated_unit_still_visible_with_include_inactive(client, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    client.patch(f"/api/units-of-measure/{kilogram_unit.id}/status", json={"is_active": False}, headers=headers)

    response = client.get(f"/api/units-of-measure/{kilogram_unit.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False
