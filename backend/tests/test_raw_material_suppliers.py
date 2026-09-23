"""Tests for docs/modules/raw_materials.md #6/#7: the Supplier <-> Raw
Material relationship (SupplierMaterial) -- the one relationship built
with real depth for this module. Covers add/list/edit/remove, admin
gating, active-and-same-organisation validation for supplier_id, the
single-preferred-supplier enforcement, uniqueness of the (supplier,
material) pair, zero-suppliers-is-valid, and the audit trail."""
from app.models.audit_event import (
    SUPPLIER_MATERIAL_ADDED,
    SUPPLIER_MATERIAL_REMOVED,
    SUPPLIER_MATERIAL_UPDATED,
    AuditEvent,
)
from app.models.supplier_material import SupplierMaterial


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _url(material_id, suffix=""):
    return f"/api/raw-materials/{material_id}/suppliers{suffix}"


# --- list (open read) -------------------------------------------------


def test_list_suppliers_requires_authentication(client, cement_raw_material):
    response = client.get(_url(cement_raw_material.id))
    assert response.status_code == 401


def test_list_suppliers_for_material_with_none_linked_returns_empty_list(client, active_user, cement_raw_material):
    """A material with zero suppliers is a valid, normal state -- no
    minimum is enforced (docs/audit/RAW_MATERIALS_AUDIT.md #5)."""
    headers = _login_headers(client)
    response = client.get(_url(cement_raw_material.id), headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_suppliers_for_material_in_other_organisation_returns_404(
    client, active_user, other_organisation, db_session
):
    from app.models.category import Category
    from app.models.raw_material import RawMaterial
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
    response = client.get(_url(other_material.id), headers=headers)
    assert response.status_code == 404


# --- add ----------------------------------------------------------------


def test_non_admin_cannot_add_supplier_relationship(client, active_user, cement_raw_material, acme_supplier):
    headers = _login_headers(client)
    response = client.post(_url(cement_raw_material.id), json={"supplier_id": acme_supplier.id}, headers=headers)
    assert response.status_code == 403


def test_admin_can_add_supplier_relationship(client, db_session, admin_user, cement_raw_material, acme_supplier):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        _url(cement_raw_material.id),
        json={
            "supplier_id": acme_supplier.id,
            "supplier_material_code": "ACME-CEM-50",
            "purchase_price": "11.00",
            "lead_time_days": 7,
            "moq": "500",
            "max_supply_quantity": "10000",
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["supplier_id"] == acme_supplier.id
    assert body["raw_material_id"] == cement_raw_material.id
    assert body["supplier_material_code"] == "ACME-CEM-50"
    assert body["lead_time_days"] == 7
    assert body["is_preferred"] is False
    assert body["is_active"] is True

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == SUPPLIER_MATERIAL_ADDED, AuditEvent.entity_id == cement_raw_material.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_add_supplier_relationship_rejects_inactive_supplier(
    client, admin_user, cement_raw_material, db_session, organisation
):
    from app.models.supplier import Supplier

    inactive_supplier = Supplier(organisation_id=organisation.id, code="SUP0002", name="Retired Vendor", is_active=False)
    db_session.add(inactive_supplier)
    db_session.commit()
    db_session.refresh(inactive_supplier)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        _url(cement_raw_material.id), json={"supplier_id": inactive_supplier.id}, headers=headers
    )
    assert response.status_code == 422


def test_add_supplier_relationship_rejects_cross_organisation_supplier(
    client, admin_user, cement_raw_material, other_organisation, db_session
):
    from app.models.supplier import Supplier

    other_supplier = Supplier(organisation_id=other_organisation.id, code="SUP0001", name="Acme Traders", is_active=True)
    db_session.add(other_supplier)
    db_session.commit()
    db_session.refresh(other_supplier)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        _url(cement_raw_material.id), json={"supplier_id": other_supplier.id}, headers=headers
    )
    assert response.status_code == 422


def test_add_supplier_relationship_rejects_duplicate_pair(client, admin_user, cement_raw_material, acme_supplier):
    headers = _login_headers(client, "admin_person")
    first = client.post(_url(cement_raw_material.id), json={"supplier_id": acme_supplier.id}, headers=headers)
    assert first.status_code == 201

    duplicate = client.post(_url(cement_raw_material.id), json={"supplier_id": acme_supplier.id}, headers=headers)
    assert duplicate.status_code == 409


def test_add_supplier_relationship_rejects_negative_price(client, admin_user, cement_raw_material, acme_supplier):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        _url(cement_raw_material.id),
        json={"supplier_id": acme_supplier.id, "purchase_price": "-1.00"},
        headers=headers,
    )
    assert response.status_code == 422


def test_multiple_suppliers_can_be_linked_to_one_material(
    client, admin_user, cement_raw_material, acme_supplier, db_session, organisation
):
    from app.models.supplier import Supplier

    second_supplier = Supplier(organisation_id=organisation.id, code="SUP0002", name="Beta Vendor", is_active=True)
    db_session.add(second_supplier)
    db_session.commit()
    db_session.refresh(second_supplier)

    headers = _login_headers(client, "admin_person")
    client.post(_url(cement_raw_material.id), json={"supplier_id": acme_supplier.id}, headers=headers)
    client.post(_url(cement_raw_material.id), json={"supplier_id": second_supplier.id}, headers=headers)

    response = client.get(_url(cement_raw_material.id), headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 2


# --- preferred-supplier enforcement --------------------------------------


def test_only_one_supplier_can_be_preferred_at_a_time(
    client, admin_user, cement_raw_material, acme_supplier, db_session, organisation
):
    """Service-side enforcement, not a DB constraint -- setting a second
    preferred supplier silently un-sets the first
    (docs/audit/RAW_MATERIALS_AUDIT.md #5)."""
    from app.models.supplier import Supplier

    second_supplier = Supplier(organisation_id=organisation.id, code="SUP0002", name="Beta Vendor", is_active=True)
    db_session.add(second_supplier)
    db_session.commit()
    db_session.refresh(second_supplier)

    headers = _login_headers(client, "admin_person")
    first = client.post(
        _url(cement_raw_material.id), json={"supplier_id": acme_supplier.id, "is_preferred": True}, headers=headers
    )
    assert first.json()["is_preferred"] is True

    second = client.post(
        _url(cement_raw_material.id), json={"supplier_id": second_supplier.id, "is_preferred": True}, headers=headers
    )
    assert second.json()["is_preferred"] is True

    first_link_id = first.json()["id"]
    db_session.expire_all()
    refreshed_first = db_session.query(SupplierMaterial).filter(SupplierMaterial.id == first_link_id).one()
    assert refreshed_first.is_preferred is False


def test_setting_preferred_via_update_unsets_the_previous_preferred(
    client, admin_user, cement_raw_material, acme_supplier, db_session, organisation
):
    from app.models.supplier import Supplier

    second_supplier = Supplier(organisation_id=organisation.id, code="SUP0002", name="Beta Vendor", is_active=True)
    db_session.add(second_supplier)
    db_session.commit()
    db_session.refresh(second_supplier)

    headers = _login_headers(client, "admin_person")
    first = client.post(
        _url(cement_raw_material.id), json={"supplier_id": acme_supplier.id, "is_preferred": True}, headers=headers
    )
    second = client.post(_url(cement_raw_material.id), json={"supplier_id": second_supplier.id}, headers=headers)

    update = client.patch(
        _url(cement_raw_material.id, f"/{second.json()['id']}"), json={"is_preferred": True}, headers=headers
    )
    assert update.status_code == 200
    assert update.json()["is_preferred"] is True

    db_session.expire_all()
    refreshed_first = db_session.query(SupplierMaterial).filter(SupplierMaterial.id == first.json()["id"]).one()
    assert refreshed_first.is_preferred is False


# --- update ---------------------------------------------------------------


def test_non_admin_cannot_edit_supplier_relationship(client, active_user, admin_user, cement_raw_material, acme_supplier):
    headers = _login_headers(client, "admin_person")
    created = client.post(_url(cement_raw_material.id), json={"supplier_id": acme_supplier.id}, headers=headers)

    member_headers = _login_headers(client)
    response = client.patch(
        _url(cement_raw_material.id, f"/{created.json()['id']}"), json={"lead_time_days": 5}, headers=member_headers
    )
    assert response.status_code == 403


def test_admin_can_edit_supplier_relationship_terms(client, db_session, admin_user, cement_raw_material, acme_supplier):
    headers = _login_headers(client, "admin_person")
    created = client.post(_url(cement_raw_material.id), json={"supplier_id": acme_supplier.id}, headers=headers)

    response = client.patch(
        _url(cement_raw_material.id, f"/{created.json()['id']}"),
        json={"lead_time_days": 3, "is_active": False},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["lead_time_days"] == 3
    assert response.json()["is_active"] is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == SUPPLIER_MATERIAL_UPDATED)
        .one()
    )
    assert event.actor_user_id == admin_user.id


def test_edit_nonexistent_link_returns_404(client, admin_user, cement_raw_material):
    headers = _login_headers(client, "admin_person")
    response = client.patch(_url(cement_raw_material.id, "/999999"), json={"lead_time_days": 3}, headers=headers)
    assert response.status_code == 404


# --- remove -----------------------------------------------------------


def test_non_admin_cannot_remove_supplier_relationship(client, active_user, admin_user, cement_raw_material, acme_supplier):
    headers = _login_headers(client, "admin_person")
    created = client.post(_url(cement_raw_material.id), json={"supplier_id": acme_supplier.id}, headers=headers)

    member_headers = _login_headers(client)
    response = client.delete(_url(cement_raw_material.id, f"/{created.json()['id']}"), headers=member_headers)
    assert response.status_code == 403


def test_admin_can_remove_supplier_relationship(client, db_session, admin_user, cement_raw_material, acme_supplier):
    headers = _login_headers(client, "admin_person")
    created = client.post(_url(cement_raw_material.id), json={"supplier_id": acme_supplier.id}, headers=headers)
    link_id = created.json()["id"]

    response = client.delete(_url(cement_raw_material.id, f"/{link_id}"), headers=headers)
    assert response.status_code == 204

    remaining = db_session.query(SupplierMaterial).filter(SupplierMaterial.id == link_id).first()
    assert remaining is None

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == SUPPLIER_MATERIAL_REMOVED, AuditEvent.entity_id == cement_raw_material.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id

    empty_list = client.get(_url(cement_raw_material.id), headers=headers)
    assert empty_list.json() == []


def test_removing_a_supplier_relationship_does_not_deactivate_the_raw_material(
    client, db_session, admin_user, cement_raw_material, acme_supplier
):
    """Deactivating/removing a supplier relationship is a separate,
    explicit action from the material's own lifecycle -- never a side
    effect (docs/modules/raw_materials.md #17)."""
    headers = _login_headers(client, "admin_person")
    created = client.post(_url(cement_raw_material.id), json={"supplier_id": acme_supplier.id}, headers=headers)
    client.delete(_url(cement_raw_material.id, f"/{created.json()['id']}"), headers=headers)

    material = client.get(f"/api/raw-materials/{cement_raw_material.id}", headers=headers)
    assert material.json()["is_active"] is True
