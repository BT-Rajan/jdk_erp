"""Sales S4: the quotation data foundation -- server-calculated amounts,
customer-scoped access, product price-range flags, explicit product
units, and immutable YY4NNNN numbers."""

from decimal import Decimal

import pytest

from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.models.audit_event import QUOTATION_CREATED, AuditEvent
from app.models.customer import Customer
from app.models.quotation import Quotation
from app.models.team import Team
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.user_team import UserTeam


def _user(db_session, organisation, username, role):
    user = User(
        organisation_id=organisation.id,
        role=role,
        full_name=username.title(),
        email=f"{username}@example.com",
        username=username,
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(db_session, organisation, widget_product, kilogram_unit):
    """Sales team (head, salesmen A and B, one customer each), an admin,
    and Widget priced 100 with a permitted range of 90-110 per kg."""
    team = Team(organisation_id=organisation.id, name="Sales", code="SALES", is_active=True)
    db_session.add(team)
    db_session.commit()
    users = {
        "head": _user(db_session, organisation, "head", MANAGER),
        "a": _user(db_session, organisation, "salesman_a", TEAM_MEMBER),
        "b": _user(db_session, organisation, "salesman_b", TEAM_MEMBER),
        "admin": _user(db_session, organisation, "boss", ADMIN),
    }
    db_session.add_all([UserTeam(user_id=users[k].id, team_id=team.id) for k in ("head", "a", "b")])
    customers = {
        "a": Customer(organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["a"].id),
        "b": Customer(organisation_id=organisation.id, code="300002", name="B Co", assigned_to_user_id=users["b"].id),
    }
    db_session.add_all(customers.values())
    widget_product.min_selling_price = Decimal("90")
    widget_product.max_selling_price = Decimal("110")
    db_session.commit()
    return users, customers, widget_product, kilogram_unit


def _line(product, unit, quantity="2", price="100"):
    return {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": unit.id, "unit_price": price}


def test_create_persists_lines_with_server_calculated_totals(client, db_session, setup):
    users, customers, product, unit = setup
    response = client.post(
        "/api/quotations",
        json={
            "customer_id": customers["a"].id,
            "lines": [_line(product, unit, "3", "100.1235"), _line(product, unit, "1", "95")],
            # Anything the server owns is ignored, never trusted.
            "quotation_number": "HACKED",
            "total_amount": "1",
            "subtotal_amount": "1",
            "status": "accepted",
        },
        headers=_headers(client, "salesman_a"),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["quotation_number"].endswith("40001") and len(body["quotation_number"]) == 7
    assert body["status"] == "draft"
    assert body["currency"] == "KWD"
    # 3 x 100.1235 = 300.3705 -> 300.371 (KWD, 3 decimals); + 95.000.
    assert [Decimal(line["line_amount"]) for line in body["lines"]] == [Decimal("300.371"), Decimal("95.000")]
    assert Decimal(body["subtotal_amount"]) == Decimal("395.371")
    assert Decimal(body["total_amount"]) == Decimal("395.371")
    assert [line["line_number"] for line in body["lines"]] == [1, 2]
    assert body["created_by_user_id"] == users["a"].id

    event = db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_CREATED).one()
    assert event.entity_id == body["id"] and event.actor_user_id == users["a"].id


def test_quotation_access_follows_customer_scope(client, setup):
    users, customers, product, unit = setup
    a, b = _headers(client, "salesman_a"), _headers(client, "salesman_b")

    # Creating for another salesman's customer is the same 404 as a missing one.
    assert client.post("/api/quotations", json={"customer_id": customers["b"].id, "lines": [_line(product, unit)]}, headers=a).status_code == 404
    mine = client.post("/api/quotations", json={"customer_id": customers["a"].id, "lines": [_line(product, unit)]}, headers=a).json()
    theirs = client.post("/api/quotations", json={"customer_id": customers["b"].id, "lines": [_line(product, unit)]}, headers=b).json()

    assert client.get(f"/api/quotations/{theirs['id']}", headers=a).status_code == 404
    assert client.get(f"/api/quotations/{theirs['id']}/lines", headers=a).status_code == 404
    assert [q["id"] for q in client.get("/api/quotations", headers=a).json()["data"]] == [mine["id"]]
    # The Department Head sees the whole team's quotations.
    head_ids = {q["id"] for q in client.get("/api/quotations", headers=_headers(client, "head")).json()["data"]}
    assert head_ids == {mine["id"], theirs["id"]}


def test_price_outside_or_without_range_is_flagged_for_admin_approval(client, db_session, setup):
    users, customers, product, unit = setup
    headers = _headers(client, "salesman_a")

    def flags(*prices):
        body = client.post(
            "/api/quotations",
            json={"customer_id": customers["a"].id, "lines": [_line(product, unit, "1", p) for p in prices]},
            headers=headers,
        ).json()
        return [line["price_approval_required"] for line in body["lines"]], body["price_approval_required"]

    # 90 and 110 are the bounds (inclusive); 89.99 below, 110.01 above.
    assert flags("90", "110") == ([False, False], False)
    assert flags("89.99", "100", "110.01") == ([True, False, True], True)

    # No full range on the product -> any price needs approval.
    product.max_selling_price = None
    db_session.commit()
    assert flags("100") == ([True], True)

    # Admin cannot set an inverted range.
    response = client.patch(
        f"/api/products/{product.id}",
        json={"min_selling_price": "120", "max_selling_price": "110"},
        headers=_headers(client, "boss"),
    )
    assert response.status_code == 422


def test_line_must_use_the_products_own_unit(client, db_session, organisation, setup):
    users, customers, product, unit = setup
    litre = UnitOfMeasure(organisation_id=organisation.id, name="Litre", code="L", is_active=True)
    db_session.add(litre)
    db_session.commit()

    response = client.post(
        "/api/quotations",
        json={"customer_id": customers["a"].id, "lines": [_line(product, litre)]},
        headers=_headers(client, "salesman_a"),
    )
    assert response.status_code == 422
    assert db_session.query(Quotation).count() == 0


def test_numbers_are_sequential_unique_and_have_no_edit_path(client, db_session, setup):
    users, customers, product, unit = setup
    headers = _headers(client, "salesman_a")
    payload = {"customer_id": customers["a"].id, "lines": [_line(product, unit)]}
    first = client.post("/api/quotations", json=payload, headers=headers).json()
    second = client.post("/api/quotations", json=payload, headers=headers).json()

    assert int(second["quotation_number"]) == int(first["quotation_number"]) + 1
    assert first["quotation_number"][2] == "4"
    # The edit path (Sales S10) never accepts a number from the client.
    assert client.patch(f"/api/quotations/{first['id']}", json={"quotation_number": "2640099"}, headers=headers).status_code == 200
    db_session.expire_all()
    assert db_session.get(Quotation, first["id"]).quotation_number == first["quotation_number"]
