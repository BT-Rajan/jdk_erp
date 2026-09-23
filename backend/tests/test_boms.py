"""Tests for docs/modules/boms.md: the single, unambiguous relationship
between a finished Product and the Raw Materials required to produce a
specified base quantity of it -- list/get (open read), admin-gated
create/edit/component management/activation, the mandatory Product<->
Material unit-conversion validation (the core of the spec's #14 test
matrix -- universal/dimensional conversion, material-specific density
and packaging conversion, and rejection when no valid conversion
exists), draft/active status gating, per-organisation product
uniqueness, stateless production requirement calculation and its
scaling formula, and the audit trail for each mutation."""
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import (
    BOM_COMPONENT_ADDED,
    BOM_COMPONENT_REMOVED,
    BOM_COMPONENT_UPDATED,
    BOM_CREATED,
    BOM_STATUS_CHANGED,
    BOM_UPDATED,
    AuditEvent,
)
from app.models.bom import Bom, BomComponent


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_bom(client, headers, product_id, base_quantity="1", notes=None):
    return client.post(
        "/api/boms", json={"product_id": product_id, "base_quantity": base_quantity, "notes": notes}, headers=headers
    )


def _add_component(client, headers, bom_id, raw_material_id, quantity):
    return client.post(
        f"/api/boms/{bom_id}/components",
        json={"raw_material_id": raw_material_id, "quantity": quantity},
        headers=headers,
    )


def _activate(client, headers, bom_id):
    return client.patch(f"/api/boms/{bom_id}/status", json={"status": "active"}, headers=headers)


# --- list / get (open read) -------------------------------------------------


def test_boms_list_requires_authentication(client, active_user):
    response = client.get("/api/boms")
    assert response.status_code == 401


def test_list_boms_returns_only_my_organisation(
    client, active_user, admin_user, product_tonne, other_organisation, db_session
):
    headers = _login_headers(client, "admin_person")
    created = _create_bom(client, headers, product_tonne.id).json()

    from app.models.category import Category
    from app.models.product import Product
    from app.models.unit import UnitOfMeasure

    other_category = Category(organisation_id=other_organisation.id, name="Cat", code="CAT1", is_active=True)
    db_session.add(other_category)
    db_session.commit()
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Tonne", code="TON", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    other_product = Product(
        organisation_id=other_organisation.id,
        code="OTH-1",
        name="Other Product",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        selling_price=1,
        is_active=True,
    )
    db_session.add(other_product)
    db_session.commit()
    other_bom = Bom(organisation_id=other_organisation.id, product_id=other_product.id, base_quantity=1)
    db_session.add(other_bom)
    db_session.commit()

    reader_headers = _login_headers(client)
    response = client.get("/api/boms", headers=reader_headers)
    assert response.status_code == 200
    bom_ids = {b["id"] for b in response.json()["data"]}
    assert bom_ids == {created["id"]}


def test_get_bom_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    from app.models.category import Category
    from app.models.product import Product
    from app.models.unit import UnitOfMeasure

    other_category = Category(organisation_id=other_organisation.id, name="Cat", code="CAT1", is_active=True)
    db_session.add(other_category)
    db_session.commit()
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Tonne", code="TON", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    other_product = Product(
        organisation_id=other_organisation.id,
        code="OTH-1",
        name="Other Product",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        selling_price=1,
        is_active=True,
    )
    db_session.add(other_product)
    db_session.commit()
    other_bom = Bom(organisation_id=other_organisation.id, product_id=other_product.id, base_quantity=1)
    db_session.add(other_bom)
    db_session.commit()
    db_session.refresh(other_bom)

    headers = _login_headers(client, "admin_person")
    response = client.get(f"/api/boms/{other_bom.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_bom_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/boms/999999", headers=headers)
    assert response.status_code == 404


def test_list_boms_filters_by_product_id(client, admin_user, product_tonne, widget_product):
    headers = _login_headers(client, "admin_person")
    bom_a = _create_bom(client, headers, product_tonne.id).json()
    _create_bom(client, headers, widget_product.id)

    response = client.get(f"/api/boms?product_id={product_tonne.id}", headers=headers)
    assert response.status_code == 200
    ids = {b["id"] for b in response.json()["data"]}
    assert ids == {bom_a["id"]}


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_bom(client, active_user, product_tonne):
    headers = _login_headers(client)
    response = _create_bom(client, headers, product_tonne.id)
    assert response.status_code == 403


def test_admin_can_create_bom(client, db_session, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    response = _create_bom(client, headers, product_tonne.id, base_quantity="1")
    assert response.status_code == 201
    body = response.json()
    assert body["product_id"] == product_tonne.id
    assert body["base_quantity"] == "1.0000"
    assert body["status"] == "draft"
    assert body["components"] == []

    event = db_session.query(AuditEvent).filter(AuditEvent.action == BOM_CREATED, AuditEvent.entity_id == body["id"]).one()
    assert event.actor_user_id == admin_user.id


def test_create_bom_rejects_zero_base_quantity(client, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    response = _create_bom(client, headers, product_tonne.id, base_quantity="0")
    assert response.status_code == 422


def test_create_bom_rejects_negative_base_quantity(client, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    response = _create_bom(client, headers, product_tonne.id, base_quantity="-1")
    assert response.status_code == 422


def test_create_bom_rejects_nonexistent_product(client, admin_user):
    headers = _login_headers(client, "admin_person")
    response = _create_bom(client, headers, 999999)
    assert response.status_code == 404


def test_create_bom_rejects_inactive_product(client, admin_user, db_session, product_tonne):
    product_tonne.is_active = False
    db_session.add(product_tonne)
    db_session.commit()

    headers = _login_headers(client, "admin_person")
    response = _create_bom(client, headers, product_tonne.id)
    assert response.status_code == 422


def test_create_bom_rejects_second_bom_for_same_product(client, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    first = _create_bom(client, headers, product_tonne.id)
    assert first.status_code == 201

    second = _create_bom(client, headers, product_tonne.id)
    assert second.status_code == 409


def test_bom_product_unique_within_organisation_but_not_across(
    db_session, organisation, other_organisation, product_tonne
):
    from app.models.category import Category
    from app.models.product import Product
    from app.models.unit import UnitOfMeasure

    bom_a = Bom(organisation_id=organisation.id, product_id=product_tonne.id, base_quantity=1)
    db_session.add(bom_a)
    db_session.commit()

    duplicate_in_same_org = Bom(organisation_id=organisation.id, product_id=product_tonne.id, base_quantity=2)
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    other_category = Category(organisation_id=other_organisation.id, name="Cat", code="CAT1", is_active=True)
    db_session.add(other_category)
    db_session.commit()
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Tonne", code="TON", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    other_product = Product(
        organisation_id=other_organisation.id,
        code="OTH-1",
        name="Other Product",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        selling_price=1,
        is_active=True,
    )
    db_session.add(other_product)
    db_session.commit()
    same_product_id_other_org = Bom(organisation_id=other_organisation.id, product_id=other_product.id, base_quantity=1)
    db_session.add(same_product_id_other_org)
    db_session.commit()  # must not raise -- uniqueness is per-organisation, and product ids differ anyway


# --- update header -------------------------------------------------------


def test_non_admin_cannot_edit_bom(client, active_user, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()

    reader_headers = _login_headers(client)
    response = client.patch(f"/api/boms/{bom['id']}", json={"notes": "hijacked"}, headers=reader_headers)
    assert response.status_code == 403


def test_admin_can_update_bom_base_quantity_and_notes(client, db_session, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()

    response = client.patch(
        f"/api/boms/{bom['id']}", json={"base_quantity": "2", "notes": "revised"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["base_quantity"] == "2.0000"
    assert response.json()["notes"] == "revised"

    event = db_session.query(AuditEvent).filter(AuditEvent.action == BOM_UPDATED, AuditEvent.entity_id == bom["id"]).one()
    assert event.actor_user_id == admin_user.id


def test_update_bom_rejects_zero_base_quantity(client, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()

    response = client.patch(f"/api/boms/{bom['id']}", json={"base_quantity": "0"}, headers=headers)
    assert response.status_code == 422


def test_update_bom_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    from app.models.category import Category
    from app.models.product import Product
    from app.models.unit import UnitOfMeasure

    other_category = Category(organisation_id=other_organisation.id, name="Cat", code="CAT1", is_active=True)
    db_session.add(other_category)
    db_session.commit()
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Tonne", code="TON", is_active=True)
    db_session.add(other_unit)
    db_session.commit()
    other_product = Product(
        organisation_id=other_organisation.id,
        code="OTH-1",
        name="Other Product",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        selling_price=1,
        is_active=True,
    )
    db_session.add(other_product)
    db_session.commit()
    other_bom = Bom(organisation_id=other_organisation.id, product_id=other_product.id, base_quantity=1)
    db_session.add(other_bom)
    db_session.commit()
    db_session.refresh(other_bom)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/boms/{other_bom.id}", json={"notes": "hijacked"}, headers=headers)
    assert response.status_code == 404


# --- components: the conversion validation matrix (docs/modules/boms.md #14) -


def test_component_accepted_with_same_unit_as_product(client, admin_user, db_session, product_tonne, mass_tonne_unit):
    """Test matrix #6/#7 baseline -- a component whose own unit IS the
    product's unit needs no conversion at all (ratio 1)."""
    from app.models.category import Category
    from app.models.raw_material import RawMaterial

    category = db_session.query(Category).filter(Category.organisation_id == product_tonne.organisation_id).first()
    material = RawMaterial(
        organisation_id=product_tonne.organisation_id,
        code="RM-SAME",
        name="Material Same Unit",
        category_id=category.id,
        unit_of_measure_id=mass_tonne_unit.id,
        is_active=True,
    )
    db_session.add(material)
    db_session.commit()
    db_session.refresh(material)

    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id, base_quantity="1").json()
    response = _add_component(client, headers, bom["id"], material.id, "0.6")
    assert response.status_code == 201
    component = response.json()["components"][0]
    assert component["conversion_ok"] is True
    assert Decimal(component["percentage"]) == Decimal("60")


def test_component_accepted_with_universal_mass_conversion(client, admin_user, product_tonne, material_m_kg):
    """Test matrix #1/#2 -- Product 1 tonne, Material M in kg, component
    quantity 600 kg -> valid via the universal dimensional ratio, 60%."""
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id, base_quantity="1").json()
    response = _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    assert response.status_code == 201
    component = response.json()["components"][0]
    assert component["conversion_ok"] is True
    assert component["conversion_error"] is None
    assert Decimal(component["percentage"]) == Decimal("60")


def test_component_rejected_with_no_valid_dimensional_conversion(
    client, admin_user, product_tonne, material_no_conversion_litre
):
    """Test matrix #3 -- Product tonne, Material litre, no material-
    specific conversion configured -> the BOM must be rejected/saved as
    incomplete rather than silently calculating an incorrect quantity."""
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id, base_quantity="1").json()
    response = _add_component(client, headers, bom["id"], material_no_conversion_litre.id, "500")
    assert response.status_code == 422
    assert "Cannot establish a valid quantity conversion" in response.json()["error"]["message"]


def test_component_accepted_with_material_specific_density_conversion(
    client, admin_user, product_tonne, material_n_litre_with_density
):
    """Test matrix #4 -- Material N in litres, 1 litre = 1.25 kg
    configured on the material itself. 480 litres = 600 kg = 60% of the
    1-tonne base."""
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id, base_quantity="1").json()
    response = _add_component(client, headers, bom["id"], material_n_litre_with_density.id, "480")
    assert response.status_code == 201
    component = response.json()["components"][0]
    assert component["conversion_ok"] is True
    assert Decimal(component["percentage"]) == Decimal("60")


def test_component_accepted_with_material_specific_packaging_conversion(
    client, admin_user, product_tonne, material_p_bag_with_packaging
):
    """Test matrix #5 -- Material P in bags, 1 bag = 25 kg configured on
    the material itself. 4 bags = 100 kg = 10% of the 1-tonne base."""
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id, base_quantity="1").json()
    response = _add_component(client, headers, bom["id"], material_p_bag_with_packaging.id, "4")
    assert response.status_code == 201
    component = response.json()["components"][0]
    assert component["conversion_ok"] is True
    assert Decimal(component["percentage"]) == Decimal("10")


def test_add_component_rejects_zero_quantity(client, admin_user, product_tonne, material_m_kg):
    """Test matrix #8."""
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    response = _add_component(client, headers, bom["id"], material_m_kg.id, "0")
    assert response.status_code == 422


def test_add_component_rejects_negative_quantity(client, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    response = _add_component(client, headers, bom["id"], material_m_kg.id, "-1")
    assert response.status_code == 422


def test_add_component_rejects_inactive_raw_material(client, admin_user, db_session, product_tonne, material_m_kg):
    material_m_kg.is_active = False
    db_session.add(material_m_kg)
    db_session.commit()

    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    response = _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    assert response.status_code == 422


def test_add_component_rejects_nonexistent_raw_material(client, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    response = _add_component(client, headers, bom["id"], 999999, "600")
    assert response.status_code == 422


def test_add_duplicate_raw_material_component_rejected(client, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    first = _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    assert first.status_code == 201

    second = _add_component(client, headers, bom["id"], material_m_kg.id, "100")
    assert second.status_code == 409


def test_non_admin_cannot_add_component(client, active_user, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()

    reader_headers = _login_headers(client)
    response = _add_component(client, reader_headers, bom["id"], material_m_kg.id, "600")
    assert response.status_code == 403


# --- component update / remove ------------------------------------------


def test_admin_can_update_component_quantity(client, db_session, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    added = _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    component_id = added.json()["components"][0]["id"]

    response = client.patch(
        f"/api/boms/{bom['id']}/components/{component_id}", json={"quantity": "700"}, headers=headers
    )
    assert response.status_code == 200
    component = response.json()["components"][0]
    assert component["quantity"] == "700.0000"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == BOM_COMPONENT_UPDATED, AuditEvent.entity_id == bom["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_update_component_rejects_zero_quantity(client, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    added = _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    component_id = added.json()["components"][0]["id"]

    response = client.patch(f"/api/boms/{bom['id']}/components/{component_id}", json={"quantity": "0"}, headers=headers)
    assert response.status_code == 422


def test_update_nonexistent_component_returns_404(client, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    response = client.patch(f"/api/boms/{bom['id']}/components/999999", json={"quantity": "1"}, headers=headers)
    assert response.status_code == 404


def test_admin_can_remove_component(client, db_session, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    added = _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    component_id = added.json()["components"][0]["id"]

    response = client.delete(f"/api/boms/{bom['id']}/components/{component_id}", headers=headers)
    assert response.status_code == 204

    remaining = client.get(f"/api/boms/{bom['id']}", headers=headers)
    assert remaining.json()["components"] == []

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == BOM_COMPONENT_REMOVED, AuditEvent.entity_id == bom["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_non_admin_cannot_remove_component(client, active_user, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    added = _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    component_id = added.json()["components"][0]["id"]

    reader_headers = _login_headers(client)
    response = client.delete(f"/api/boms/{bom['id']}/components/{component_id}", headers=reader_headers)
    assert response.status_code == 403


# --- status / activation (docs/modules/boms.md #9/#10) ----------------------


def test_non_admin_cannot_change_bom_status(client, active_user, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    _add_component(client, headers, bom["id"], material_m_kg.id, "600")

    reader_headers = _login_headers(client)
    response = _activate(client, reader_headers, bom["id"])
    assert response.status_code == 403


def test_activate_bom_rejects_status_with_no_components(client, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()

    response = _activate(client, headers, bom["id"])
    assert response.status_code == 400


def test_admin_can_activate_valid_bom(client, db_session, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    _add_component(client, headers, bom["id"], material_m_kg.id, "600")

    response = _activate(client, headers, bom["id"])
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == BOM_STATUS_CHANGED, AuditEvent.entity_id == bom["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_activate_bom_rejects_status_when_a_component_conversion_is_no_longer_valid(
    client, admin_user, product_tonne, material_m_kg, bag_unit
):
    """Defensive re-check at activation time -- a component was valid
    when added, but the material's own unit was changed afterward to one
    with no resolvable conversion to the Product's unit."""
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    _add_component(client, headers, bom["id"], material_m_kg.id, "600")

    repoint = client.patch(
        f"/api/raw-materials/{material_m_kg.id}", json={"unit_of_measure_id": bag_unit.id}, headers=headers
    )
    assert repoint.status_code == 200

    response = _activate(client, headers, bom["id"])
    assert response.status_code == 422


def test_bom_can_be_moved_back_to_draft_without_validation(client, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    _activate(client, headers, bom["id"])

    response = client.patch(f"/api/boms/{bom['id']}/status", json={"status": "draft"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "draft"


def test_change_bom_status_rejects_invalid_status_value(client, admin_user, product_tonne):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    response = client.patch(f"/api/boms/{bom['id']}/status", json={"status": "bogus"}, headers=headers)
    assert response.status_code == 422


# --- production requirement calculation (docs/modules/boms.md #7) -----------


def test_calculate_requirements_rejects_draft_bom(client, admin_user, active_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    _add_component(client, headers, bom["id"], material_m_kg.id, "600")

    reader_headers = _login_headers(client)
    response = client.post(
        f"/api/boms/{bom['id']}/calculate-requirements", json={"production_quantity": "1"}, headers=reader_headers
    )
    assert response.status_code == 400


def test_calculate_requirements_scales_production_quantity(
    client, admin_user, active_user, product_tonne, material_m_kg
):
    """Test matrix #2/#9 -- BOM 1 tonne -> 600 kg M, production order for
    2.5 tonnes -> 600 * 2.5 / 1 = 1500 kg, exactly the spec's own worked
    example."""
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id, base_quantity="1").json()
    _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    _activate(client, headers, bom["id"])

    reader_headers = _login_headers(client)
    response = client.post(
        f"/api/boms/{bom['id']}/calculate-requirements", json={"production_quantity": "2.5"}, headers=reader_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == product_tonne.id
    requirement = body["requirements"][0]
    assert requirement["raw_material_id"] == material_m_kg.id
    assert Decimal(requirement["required_quantity"]) == Decimal("1500")
    assert requirement["unit_of_measure_id"] == material_m_kg.unit_of_measure_id


def test_calculate_requirements_keeps_each_component_in_its_own_unit(
    client, admin_user, product_tonne, material_m_kg, material_p_bag_with_packaging
):
    """Test matrix #5/#7 -- Material P's requirement stays in bags (its
    own native unit), never converted to the Product's unit or the other
    component's unit, computed independently per component."""
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id, base_quantity="1").json()
    _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    _add_component(client, headers, bom["id"], material_p_bag_with_packaging.id, "4")
    _activate(client, headers, bom["id"])

    response = client.post(f"/api/boms/{bom['id']}/calculate-requirements", json={"production_quantity": "2"}, headers=headers)
    assert response.status_code == 200
    requirements = {r["raw_material_id"]: r for r in response.json()["requirements"]}
    assert Decimal(requirements[material_m_kg.id]["required_quantity"]) == Decimal("1200")
    assert requirements[material_m_kg.id]["unit_of_measure_id"] == material_m_kg.unit_of_measure_id
    assert Decimal(requirements[material_p_bag_with_packaging.id]["required_quantity"]) == Decimal("8")
    assert requirements[material_p_bag_with_packaging.id]["unit_of_measure_id"] == material_p_bag_with_packaging.unit_of_measure_id


def test_calculate_requirements_rejects_zero_production_quantity(client, admin_user, product_tonne, material_m_kg):
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id).json()
    _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    _activate(client, headers, bom["id"])

    response = client.post(f"/api/boms/{bom['id']}/calculate-requirements", json={"production_quantity": "0"}, headers=headers)
    assert response.status_code == 422


def test_calculate_requirements_is_stateless_and_reflects_live_bom_state(
    client, admin_user, product_tonne, material_m_kg
):
    """docs/modules/boms.md #11 -- calculation never persists a
    "production order" of its own; it always reflects the BOM's current
    component data, live, with no memory of a prior answer. (A future
    Production Order module is responsible for snapshotting whatever it
    reads here onto its own transaction row -- see the final report's
    note on docs/modules/boms.md #10's snapshot obligation.)"""
    headers = _login_headers(client, "admin_person")
    bom = _create_bom(client, headers, product_tonne.id, base_quantity="1").json()
    added = _add_component(client, headers, bom["id"], material_m_kg.id, "600")
    component_id = added.json()["components"][0]["id"]
    _activate(client, headers, bom["id"])

    first = client.post(f"/api/boms/{bom['id']}/calculate-requirements", json={"production_quantity": "1"}, headers=headers)
    assert Decimal(first.json()["requirements"][0]["required_quantity"]) == Decimal("600")

    client.patch(f"/api/boms/{bom['id']}/status", json={"status": "draft"}, headers=headers)
    client.patch(f"/api/boms/{bom['id']}/components/{component_id}", json={"quantity": "700"}, headers=headers)
    client.patch(f"/api/boms/{bom['id']}/status", json={"status": "active"}, headers=headers)

    second = client.post(f"/api/boms/{bom['id']}/calculate-requirements", json={"production_quantity": "1"}, headers=headers)
    assert Decimal(second.json()["requirements"][0]["required_quantity"]) == Decimal("700")
