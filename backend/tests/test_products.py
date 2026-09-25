"""Tests for docs/modules/products.md: organisation-scoped Product master
-- list/get (open read), admin-gated create/edit/activate-deactivate,
required active Category/UnitOfMeasure FK validation, per-organisation
code/name uniqueness, immutable code, lead-time/price validation, and the
audit trail for each mutation."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.models.audit_event import PRODUCT_CREATED, PRODUCT_STATUS_CHANGED, PRODUCT_UPDATED, AuditEvent
from app.models.product import Product


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- list / get (open read) ------------------------------------------------


def test_products_list_requires_authentication(client, active_user):
    response = client.get("/api/products")
    assert response.status_code == 401


def test_list_products_returns_only_my_organisation(
    client, active_user, widget_product, other_organisation, db_session
):
    from app.models.category import Category
    from app.models.unit import UnitOfMeasure

    other_category = Category(organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_category, other_unit])
    db_session.commit()
    other_product = Product(
        organisation_id=other_organisation.id,
        code="PRD001",
        name="Widget",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        selling_price=50,
        is_active=True,
    )
    db_session.add(other_product)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/products", headers=headers)

    assert response.status_code == 200
    product_ids = {p["id"] for p in response.json()["data"]}
    assert product_ids == {widget_product.id}


def test_get_product_in_other_organisation_returns_404(
    client, active_user, other_organisation, db_session
):
    from app.models.category import Category
    from app.models.unit import UnitOfMeasure

    other_category = Category(organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_category, other_unit])
    db_session.commit()
    other_product = Product(
        organisation_id=other_organisation.id,
        code="PRD001",
        name="Widget",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        selling_price=50,
        is_active=True,
    )
    db_session.add(other_product)
    db_session.commit()
    db_session.refresh(other_product)

    headers = _login_headers(client)
    response = client.get(f"/api/products/{other_product.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_product_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/products/999999", headers=headers)
    assert response.status_code == 404


def test_list_products_excludes_inactive_by_default(client, active_user, organisation, electronics_category, kilogram_unit, db_session):
    inactive = Product(
        organisation_id=organisation.id,
        code="PRD999",
        name="Discontinued Gadget",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        selling_price=10,
        is_active=False,
    )
    db_session.add(inactive)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/products", headers=headers)
    names = {p["name"] for p in response.json()["data"]}
    assert "Discontinued Gadget" not in names

    with_inactive = client.get("/api/products?include_inactive=true", headers=headers)
    names_with_inactive = {p["name"] for p in with_inactive.json()["data"]}
    assert "Discontinued Gadget" in names_with_inactive


def test_list_products_search_narrows_by_name_or_code(client, active_user, widget_product, organisation, electronics_category, kilogram_unit, db_session):
    other = Product(
        organisation_id=organisation.id,
        code="PRD002",
        name="Gizmo",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        selling_price=20,
        is_active=True,
    )
    db_session.add(other)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/products?q=widget", headers=headers)
    names = {p["name"] for p in response.json()["data"]}
    assert names == {"Widget"}


# --- uniqueness (DB level) --------------------------------------------------


def test_product_code_unique_within_organisation_but_not_across(
    db_session, organisation, other_organisation, electronics_category, kilogram_unit
):
    from app.models.category import Category
    from app.models.unit import UnitOfMeasure

    product_a = Product(
        organisation_id=organisation.id,
        code="PRD001",
        name="Widget",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        selling_price=100,
        is_active=True,
    )
    db_session.add(product_a)
    db_session.commit()

    duplicate_in_same_org = Product(
        organisation_id=organisation.id,
        code="PRD001",
        name="Different Widget",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        selling_price=100,
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
    same_code_other_org = Product(
        organisation_id=other_organisation.id,
        code="PRD001",
        name="Widget",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        selling_price=100,
        is_active=True,
    )
    db_session.add(same_code_other_org)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


def test_product_name_unique_within_organisation(db_session, organisation, electronics_category, kilogram_unit, widget_product):
    duplicate_name = Product(
        organisation_id=organisation.id,
        code="PRD002",
        name="Widget",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        selling_price=100,
        is_active=True,
    )
    db_session.add(duplicate_name)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# --- create ------------------------------------------------------------


def test_non_admin_cannot_create_product(client, active_user, electronics_category, kilogram_unit):
    headers = _login_headers(client)
    response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "100.00",
        },
        headers=headers,
    )
    assert response.status_code == 403


def test_create_product_requires_authentication(client, admin_user, electronics_category, kilogram_unit):
    response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "100.00",
        },
    )
    assert response.status_code == 401


def test_admin_can_create_product(client, db_session, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "description": "A standard widget",
            "selling_price": "149.99",
            "manufacturing_lead_time_days": 10,
            "customer_lead_time_days": 15,
        },
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    # code is system-generated: prefix "2" + a 5-digit per-organisation
    # sequence (per explicit user instruction) -- never caller-supplied.
    assert body["code"] == "200001"
    assert body["name"] == "Widget"
    assert body["selling_price"] == "149.99"
    assert body["manufacturing_lead_time_days"] == 10
    assert body["customer_lead_time_days"] == 15
    assert body["is_active"] is True
    assert body["organisation_id"] == admin_user.organisation_id

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PRODUCT_CREATED, AuditEvent.entity_id == body["id"])
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "200001" in event.details


def test_create_product_ignores_a_caller_supplied_code(client, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "code": "HACKED",
            "name": "Widget",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "100.00",
        },
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["code"] == "200001"


def test_create_product_rejects_blank_name(client, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "name": "   ",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "100.00",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_product_rejects_negative_selling_price(client, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "-1.00",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_product_rejects_negative_lead_time(client, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "100.00",
            "manufacturing_lead_time_days": -5,
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_product_generates_sequential_codes(client, admin_user, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    payload = {
        "category_id": electronics_category.id,
        "unit_of_measure_id": kilogram_unit.id,
        "selling_price": "100.00",
    }
    first = client.post("/api/products", json={**payload, "name": "Widget"}, headers=headers)
    second = client.post("/api/products", json={**payload, "name": "Gadget"}, headers=headers)
    assert first.json()["code"] == "200001"
    assert second.json()["code"] == "200002"


def test_create_product_rejects_duplicate_name(client, admin_user, widget_product, electronics_category, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "name": widget_product.name,
            "category_id": electronics_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "100.00",
        },
        headers=headers,
    )
    assert response.status_code == 409


def test_create_product_rejects_nonexistent_category(client, admin_user, kilogram_unit):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "category_id": 999999,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "100.00",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_product_rejects_inactive_category(client, admin_user, db_session, organisation, kilogram_unit):
    from app.models.category import Category

    inactive_category = Category(organisation_id=organisation.id, name="Discontinued", code="DISC", is_active=False)
    db_session.add(inactive_category)
    db_session.commit()
    db_session.refresh(inactive_category)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "category_id": inactive_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "100.00",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_product_rejects_nonexistent_unit(client, admin_user, electronics_category):
    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "category_id": electronics_category.id,
            "unit_of_measure_id": 999999,
            "selling_price": "100.00",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_product_rejects_cross_organisation_category(
    client, admin_user, other_organisation, kilogram_unit, db_session
):
    from app.models.category import Category

    other_category = Category(organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    db_session.add(other_category)
    db_session.commit()
    db_session.refresh(other_category)

    headers = _login_headers(client, "admin_person")
    response = client.post(
        "/api/products",
        json={
            "name": "Widget",
            "category_id": other_category.id,
            "unit_of_measure_id": kilogram_unit.id,
            "selling_price": "100.00",
        },
        headers=headers,
    )
    assert response.status_code == 422


def test_create_product_in_one_organisation_does_not_block_another(
    client, db_session, admin_user, widget_product, other_organisation
):
    """Cross-org isolation on the write path, not just reads."""
    from app.core.security import hash_password
    from app.core.roles import ADMIN
    from app.models.category import Category
    from app.models.unit import UnitOfMeasure
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
    other_category = Category(organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_admin, other_category, other_unit])
    db_session.commit()
    db_session.refresh(other_category)
    db_session.refresh(other_unit)

    headers = _login_headers(client, "other_admin")
    response = client.post(
        "/api/products",
        json={
            "code": widget_product.code,
            "name": widget_product.name,
            "category_id": other_category.id,
            "unit_of_measure_id": other_unit.id,
            "selling_price": "100.00",
        },
        headers=headers,
    )
    assert response.status_code == 201


# --- update ------------------------------------------------------------


def test_non_admin_cannot_edit_product(client, active_user, widget_product):
    headers = _login_headers(client)
    response = client.patch(f"/api/products/{widget_product.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_edit_product(client, db_session, admin_user, widget_product):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/products/{widget_product.id}",
        json={"name": "Super Widget", "selling_price": "199.99", "customer_lead_time_days": 20},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Super Widget"
    assert body["selling_price"] == "199.99"
    assert body["customer_lead_time_days"] == 20
    # code was never sent -- a PATCH, not a full replace, and code has no
    # update path at all (docs/audit/PRODUCTS_AUDIT.md #2).
    assert body["code"] == widget_product.code

    db_session.refresh(widget_product)
    assert widget_product.name == "Super Widget"

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PRODUCT_UPDATED, AuditEvent.entity_id == widget_product.id)
        .one()
    )
    assert event.actor_user_id == admin_user.id
    assert "name:" in event.details


def test_admin_can_change_unit_of_measure_when_no_bom_exists(client, admin_user, widget_product, mass_kilogram_unit):
    """Control case: unit_of_measure_id stays editable on a product with
    no BOM -- existing behaviour must be unaffected by the new guard."""
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/products/{widget_product.id}",
        json={"unit_of_measure_id": mass_kilogram_unit.id},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["unit_of_measure_id"] == mass_kilogram_unit.id


def test_edit_product_rejects_unit_change_once_a_bom_exists(client, admin_user, product_tonne, mass_kilogram_unit):
    """Bom.base_quantity stores no unit of its own -- it implicitly means
    "in the product's own unit." Once a BOM exists, changing the
    product's unit must be rejected, not silently reinterpret
    base_quantity in the new unit."""
    headers = _login_headers(client, "admin_person")
    create = client.post(
        "/api/boms", json={"product_id": product_tonne.id, "base_quantity": "1"}, headers=headers
    )
    assert create.status_code == 201

    response = client.patch(
        f"/api/products/{product_tonne.id}",
        json={"unit_of_measure_id": mass_kilogram_unit.id},
        headers=headers,
    )
    assert response.status_code == 422


def test_edit_product_code_is_not_accepted(client, admin_user, widget_product):
    """ProductUpdateRequest has no `code` field at all -- sending one is
    silently ignored by pydantic (extra fields dropped), not an error."""
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/products/{widget_product.id}", json={"code": "CHANGED", "name": "Still Widget"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["code"] == widget_product.code


def test_edit_product_rejects_blank_name(client, admin_user, widget_product):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/products/{widget_product.id}", json={"name": "   "}, headers=headers)
    assert response.status_code == 422


def test_edit_product_rejects_negative_selling_price(client, admin_user, widget_product):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/products/{widget_product.id}", json={"selling_price": "-5.00"}, headers=headers)
    assert response.status_code == 422


def test_edit_product_rejects_inactive_unit(client, admin_user, widget_product, db_session, organisation):
    from app.models.unit import UnitOfMeasure

    inactive_unit = UnitOfMeasure(organisation_id=organisation.id, name="Ton", code="TON", is_active=False)
    db_session.add(inactive_unit)
    db_session.commit()
    db_session.refresh(inactive_unit)

    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/products/{widget_product.id}", json={"unit_of_measure_id": inactive_unit.id}, headers=headers
    )
    assert response.status_code == 422


def test_edit_product_rejects_a_name_already_used_by_another_product(
    client, db_session, admin_user, widget_product, organisation, electronics_category, kilogram_unit
):
    other = Product(
        organisation_id=organisation.id,
        code="PRD002",
        name="Gizmo",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        selling_price=10,
        is_active=True,
    )
    db_session.add(other)
    db_session.commit()
    db_session.refresh(other)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/products/{other.id}", json={"name": widget_product.name}, headers=headers)
    assert response.status_code == 409

    db_session.refresh(other)
    assert other.name == "Gizmo"


def test_edit_product_in_other_organisation_returns_404(client, admin_user, other_organisation, db_session):
    from app.models.category import Category
    from app.models.unit import UnitOfMeasure

    other_category = Category(organisation_id=other_organisation.id, name="Electronics", code="OTH1", is_active=True)
    other_unit = UnitOfMeasure(organisation_id=other_organisation.id, name="Kilogram", code="KG", is_active=True)
    db_session.add_all([other_category, other_unit])
    db_session.commit()
    other_product = Product(
        organisation_id=other_organisation.id,
        code="PRD001",
        name="Widget",
        category_id=other_category.id,
        unit_of_measure_id=other_unit.id,
        selling_price=50,
        is_active=True,
    )
    db_session.add(other_product)
    db_session.commit()
    db_session.refresh(other_product)

    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/products/{other_product.id}", json={"name": "Hijacked"}, headers=headers)
    assert response.status_code == 404


def test_edit_product_ignores_id_and_organisation_id_in_the_payload(
    client, db_session, admin_user, widget_product, other_organisation
):
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/products/{widget_product.id}",
        json={"id": 999999, "organisation_id": other_organisation.id, "name": "Still Mine"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == widget_product.id

    db_session.refresh(widget_product)
    assert widget_product.name == "Still Mine"
    assert widget_product.organisation_id != other_organisation.id


# --- activate / deactivate ----------------------------------------------


def test_non_admin_cannot_change_product_status(client, active_user, widget_product):
    headers = _login_headers(client)
    response = client.patch(f"/api/products/{widget_product.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 403


def test_admin_can_deactivate_and_reactivate_product(client, db_session, admin_user, widget_product):
    headers = _login_headers(client, "admin_person")

    deactivate = client.patch(f"/api/products/{widget_product.id}/status", json={"is_active": False}, headers=headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    db_session.refresh(widget_product)
    assert widget_product.is_active is False

    event = (
        db_session.query(AuditEvent)
        .filter(AuditEvent.action == PRODUCT_STATUS_CHANGED, AuditEvent.entity_id == widget_product.id)
        .first()
    )
    assert event is not None
    assert event.actor_user_id == admin_user.id
    assert event.details == "is_active: False"

    reactivate = client.patch(f"/api/products/{widget_product.id}/status", json={"is_active": True}, headers=headers)
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


def test_deactivated_product_still_visible_with_include_inactive(client, admin_user, widget_product):
    headers = _login_headers(client, "admin_person")
    client.patch(f"/api/products/{widget_product.id}/status", json={"is_active": False}, headers=headers)

    response = client.get(f"/api/products/{widget_product.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False


# --- historical integrity (docs/modules/products.md #13) -------------------


def test_changing_selling_price_does_not_retroactively_change_prior_reads(client, admin_user, widget_product):
    """Product only exposes its current/default price -- there is no
    transaction table yet to snapshot against, but this pins down that
    the endpoint always returns Product's live current value (never a
    cached/frozen one), so a future Quotation/Order module knows it must
    snapshot the price itself rather than relying on this endpoint for
    historical accuracy."""
    headers = _login_headers(client, "admin_person")
    before = client.get(f"/api/products/{widget_product.id}", headers=headers)
    assert before.json()["selling_price"] == "100.00"

    client.patch(f"/api/products/{widget_product.id}", json={"selling_price": "250.00"}, headers=headers)

    after = client.get(f"/api/products/{widget_product.id}", headers=headers)
    assert after.json()["selling_price"] == "250.00"
