"""Tests for docs/modules/raw_materials.md: organisation-scoped Raw
Material master -- list/get (open read), admin-gated create/edit/
activate-deactivate, required active Category/UnitOfMeasure FK
validation, per-organisation code/name uniqueness, immutable code, and
the audit trail for each mutation. Mirrors test_products.py's coverage
shape -- Raw Material follows the same admin-gated CRUD pattern."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import RAW_MATERIAL_CREATED, RAW_MATERIAL_STATUS_CHANGED, RAW_MATERIAL_UPDATED, AuditEvent
from app.models.raw_material import RawMaterial


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- list / get (open read) ------------------------------------------------


def test_raw_materials_list_requires_authentication(client, active_user):
    response = client.get("/api/raw-materials")
    assert response.status_code == 401


def test_list_raw_materials_returns_only_my_organisation(
    client, active_user, cement_raw_material, other_organisation, db_session
):
    from app.models.category import Category
    from app.models.unit import UnitOfMeasure

    other_category = Category(organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_category, other_unit])
    db_session.commit()
    other_material = RawMaterial(
        organisation_id=other_organisation.id,
        code="RM001",
        name="Cement",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(other_material)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/raw-materials", headers=headers)

    assert response.status_code == 200
    material_ids = {m["id"] for m in response.json()["data"]}
    assert material_ids == {cement_raw_material.id}


def test_get_raw_material_in_other_organisation_returns_404(client, active_user, other_organisation, db_session):
    from app.models.category import Category
    from app.models.unit import UnitOfMeasure

    other_category = Category(organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_category, other_unit])
    db_session.commit()
    other_material = RawMaterial(
        organisation_id=other_organisation.id,
        code="RM001",
        name="Cement",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(other_material)
    db_session.commit()
    db_session.refresh(other_material)

    headers = _login_headers(client)
    response = client.get(f"/api/raw-materials/{other_material.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_raw_material_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/raw-materials/999999", headers=headers)
    assert response.status_code == 404


def test_list_raw_materials_excludes_inactive_by_default(
    client, active_user, organisation, electronics_category, kilogram_unit, db_session
):
    inactive = RawMaterial(
        organisation_id=organisation.id,
        code="RM999",
        name="Discontinued Resin",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        is_active=False,
    )
    db_session.add(inactive)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/raw-materials", headers=headers)
    names = {m["name"] for m in response.json()["data"]}
    assert "Discontinued Resin" not in names

    with_inactive = client.get("/api/raw-materials?include_inactive=true", headers=headers)
    names_with_inactive = {m["name"] for m in with_inactive.json()["data"]}
    assert "Discontinued Resin" in names_with_inactive


def test_list_raw_materials_search_narrows_by_name_or_code(
    client, active_user, cement_raw_material, organisation, electronics_category, kilogram_unit, db_session
):
    other = RawMaterial(
        organisation_id=organisation.id,
        code="RM002",
        name="Sand",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        is_active=True,
    )
    db_session.add(other)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/raw-materials?q=cement", headers=headers)
    names = {m["name"] for m in response.json()["data"]}
    assert names == {"Cement"}


# --- uniqueness (DB level) --------------------------------------------------


def test_raw_material_code_unique_within_organisation_but_not_across(
    db_session, organisation, other_organisation, electronics_category, kilogram_unit
):
    from app.models.category import Category
    from app.models.unit import UnitOfMeasure

    material_a = RawMaterial(
        organisation_id=organisation.id,
        code="RM001",
        name="Cement",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        is_active=True,
    )
    db_session.add(material_a)
    db_session.commit()

    duplicate_in_same_org = RawMaterial(
        organisation_id=organisation.id,
        code="RM001",
        name="Different Material",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        is_active=True,
    )
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    other_category = Category(organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_category, other_unit])
    db_session.commit()
    same_code_other_org = RawMaterial(
        organisation_id=other_organisation.id,
        code="RM001",
        name="Cement",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(same_code_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


def test_raw_material_name_unique_within_organisation(
    db_session, organisation, electronics_category, kilogram_unit, cement_raw_material
):
    duplicate_name = RawMaterial(
        organisation_id=organisation.id,
        code="RM002",
        name="Cement",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        is_active=True,
    )
    db_session.add(duplicate_name)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_raw_material(client, active_user, electronics_category, kilogram_unit):
    headers = _login_headers(client)
    response = client.post(
        "/api/raw-materials",
        json={
            "name": "Cement",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_create_raw_material_requires_authentication(client, admin_user, electronics_category, kilogram_unit):
    response = client.post(
        "/api/raw-materials",
        json={
            "name": "Cement",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
        },
    )
    assert response.status_code == 401


def test_admin_can_create_raw_material(client, db_session, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={
            "name": "Cement",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "description": "Portland cement, 50kg bags",
            "reference_cost": "12.50",
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    # code is system-generated: prefix "1" + a 5-digit per-organisation
    # sequence (per explicit user instruction) -- never caller-supplied.
    assert body["code"] == "100001"
    assert body["name"] == "Cement"
    assert body["reference_cost"] == "12.5000"
    assert body["is_active"] is True
    assert body["organisation_id"] == admin_user.organisation_id

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == RAW_MATERIAL_CREATED, AuditEvent.entity_id == body["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "100001" in event.details


def test_create_raw_material_ignores_a_caller_supplied_code(client, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={"code": "HACKED", "name": "Cement", "category_id": electronics_category.id, "unit_of_measure_id": kilogram_unit.id},
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["code"] == "100001"


def test_create_raw_material_rejects_negative_reference_cost(client, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={
            "name": "Cement",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "reference_cost": "-1.00",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_raw_material_generates_sequential_codes(client, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    payload = {"category_id": electronics_category.id, "unit_of_measure_id": kilogram_unit.id}
    first = client.post("/api/raw-materials", json={**payload, "name": "Cement"}, headers=headers)
    second = client.post("/api/raw-materials", json={**payload, "name": "Sand"}, headers=headers)
    assert first.json()["code"] == "100001"
    assert second.json()["code"] == "100002"


def test_create_raw_material_rejects_inactive_category(client, admin_user, db_session, organisation, kilogram_unit):
    from app.models.category import Category

    inactive_category = Category(organisation_id=organisation.id, name="Discontinued", code="DISC", is_active=False)
    db_session.add(inactive_category)
    db_session.commit()
    db_session.refresh(inactive_category)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={
            "name": "Cement",
            "category_id": inactive_category.id,
            "unit_of_measure_id": kilogram_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_raw_material_rejects_cross_organisation_unit(
    client, admin_user, other_organisation, electronics_category, db_session
):
    from app.models.unit import UnitOfMeasure

    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    db_session.refresh(other_unit)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={
            "name": "Cement",
            "category_id": electronics_category.id,
            "unit_of_measure_id": other_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 422


# --- alternate conversion (docs/modules/boms.md #3/#5) ----------------------


def test_admin_can_create_raw_material_with_alternate_conversion(
    client, db_session, admin_user, electronics_category, volume_litre_unit, mass_kilogram_unit
):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={
            "code": "RM-N",
            "name": "Material N",
            "category_id": electronics_category.id,
            "unit_of_measure_id": volume_litre_unit.id,
            "alternate_conversion_unit_of_measure_id": mass_kilogram_unit.id,
            "alternate_conversion_factor": "1.25",
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["alternate_conversion_unit_of_measure_id"] == mass_kilogram_unit.id
    assert body["alternate_conversion_factor"] == "1.250000"


def test_create_raw_material_rejects_alternate_unit_without_factor(
    client, admin_user, electronics_category, volume_litre_unit, mass_kilogram_unit
):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={
            "code": "RM-N",
            "name": "Material N",
            "category_id": electronics_category.id,
            "unit_of_measure_id": volume_litre_unit.id,
            "alternate_conversion_unit_of_measure_id": mass_kilogram_unit.id,
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_raw_material_rejects_alternate_factor_without_unit(
    client, admin_user, electronics_category, volume_litre_unit
):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={
            "code": "RM-N",
            "name": "Material N",
            "category_id": electronics_category.id,
            "unit_of_measure_id": volume_litre_unit.id,
            "alternate_conversion_factor": "1.25",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_raw_material_rejects_non_positive_alternate_factor(
    client, admin_user, electronics_category, volume_litre_unit, mass_kilogram_unit
):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={
            "code": "RM-N",
            "name": "Material N",
            "category_id": electronics_category.id,
            "unit_of_measure_id": volume_litre_unit.id,
            "alternate_conversion_unit_of_measure_id": mass_kilogram_unit.id,
            "alternate_conversion_factor": "0",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_raw_material_rejects_alternate_unit_same_as_own_unit(
    client, admin_user, electronics_category, mass_kilogram_unit
):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/raw-materials",
        json={
            "code": "RM-M",
            "name": "Material M",
            "category_id": electronics_category.id,
            "unit_of_measure_id": mass_kilogram_unit.id,
            "alternate_conversion_unit_of_measure_id": mass_kilogram_unit.id,
            "alternate_conversion_factor": "1",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_admin_can_edit_raw_material_to_add_alternate_conversion(
    client, admin_user, cement_raw_material, mass_kilogram_unit, db_session, organisation
):
    from app.models.unit import UnitOfMeasure

    bag = UnitOfMeasure(organisation_id=organisation.id, name="Bag", code="BAG", is_active=True)
    db_session.add(bag)
    db_session.commit()
    db_session.refresh(bag)

    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}",
        json={"alternate_conversion_unit_of_measure_id": mass_kilogram_unit.id, "alternate_conversion_factor": "25"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["alternate_conversion_factor"] == "25.000000"


def test_edit_raw_material_rejects_adding_only_alternate_unit(client, admin_user, cement_raw_material, mass_kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}",
        json={"alternate_conversion_unit_of_measure_id": mass_kilogram_unit.id},
        headers=headers,
    )
    assert response.status_code == 422


def test_edit_raw_material_rejects_adding_only_alternate_factor(client, admin_user, cement_raw_material):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}",
        json={"alternate_conversion_factor": "25"},
        headers=headers,
    )
    assert response.status_code == 422


def test_edit_raw_material_rejects_own_unit_changed_to_match_existing_alternate_unit(
    client, admin_user, cement_raw_material, mass_kilogram_unit
):
    """Changing only unit_of_measure_id (not the alternate fields) must
    still be checked against an already-configured alternate conversion
    -- otherwise a material could end up with
    alternate_conversion_unit_of_measure_id == unit_of_measure_id (e.g.
    "1 BAG = 25 BAG"), the exact half-configured/self-referential state
    create-time validation already rejects."""
    headers = _login_headers(client, "admin_person")
    add_alternate = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}",
        json={"alternate_conversion_unit_of_measure_id": mass_kilogram_unit.id, "alternate_conversion_factor": "25"},
        headers=headers,
    )
    assert add_alternate.status_code == 200

    response = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}",
        json={"unit_of_measure_id": mass_kilogram_unit.id},
        headers=headers,
    )
    assert response.status_code == 422


# --- update ------------------------------------------------------------


def test_non_admin_cannot_edit_raw_material(client, active_user, cement_raw_material):
    headers = _login_headers(client)
    response = client.patch(f"/api/raw-materials/{cement_raw_material.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_edit_raw_material(client, db_session, admin_user, cement_raw_material):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}",
        json={"name": "Portland Cement", "reference_cost": "15.00"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Portland Cement"
    assert body["reference_cost"] == "15.0000"
    # code was never sent -- a PATCH, not a full replace, and code has no
    # update path at all (docs/audit/RAW_MATERIALS_AUDIT.md #2).
    assert body["code"] == cement_raw_material.code

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == RAW_MATERIAL_UPDATED, AuditEvent.entity_id == cement_raw_material.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_edit_raw_material_code_is_not_accepted(client, admin_user, cement_raw_material):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}", json={"code": "CHANGED", "name": "Still Cement"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["code"] == cement_raw_material.code


def test_edit_raw_material_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    from app.models.category import Category
    from app.models.unit import UnitOfMeasure

    other_category = Category(organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_category, other_unit])
    db_session.commit()
    other_material = RawMaterial(
        organisation_id=other_organisation.id,
        code="RM001",
        name="Cement",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        is_active=True,
    )
    db_session.add(other_material)
    db_session.commit()
    db_session.refresh(other_material)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/raw-materials/{other_material.id}", json={"name": "Hijacked"}, headers=headers)
    assert response.status_code == 404


# --- activate / deactivate ----------------------------------------------


def test_non_admin_cannot_change_raw_material_status(client, active_user, cement_raw_material):
    headers = _login_headers(client)
    response = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}/status", json={"is_active": False}, headers=headers
    )
    assert response.status_code == 403


def test_admin_can_deactivate_and_reactivate_raw_material(client, db_session, admin_user, cement_raw_material):
    headers = _login_headers(client, "admin_person")

    deactivate = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}/status", json={"is_active": False}, headers=headers
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == RAW_MATERIAL_STATUS_CHANGED, AuditEvent.entity_id == cement_raw_material.id)
        .first()
    )
    assert event is not None
    assert event.actor_user_id == admin_user.id

    reactivate = client.patch(
        f"/api/raw-materials/{cement_raw_material.id}/status", json={"is_active": True}, headers=headers
    )
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


def test_deactivated_raw_material_still_visible_with_include_inactive(client, admin_user, cement_raw_material):
    headers = _login_headers(client, "admin_person")
    client.patch(f"/api/raw-materials/{cement_raw_material.id}/status", json={"is_active": False}, headers=headers)

    response = client.get(f"/api/raw-materials/{cement_raw_material.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False
