"""Sales S6: the same-day Finished Goods gate -- FG availability only,
all-or-nothing across lines, Admin-only override, read-only on stock."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import QUOTATION_SAME_DAY_OVERRIDE_DECIDED, AuditEvent
from app.models.customer import Customer
from app.models.finished_goods_inventory import FinishedGoodsInventory, FinishedGoodsMovement
from app.models.product import Product
from app.models.team import Team
from app.models.unit import UnitOfMeasure
from app.models.user import User
from app.models.user_team import UserTeam
from app.services import finished_goods_inventory_service, working_calendar_service

MONDAY = date(2026, 9, 28)
MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


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
def setup(db_session, organisation, widget_product, kilogram_unit, electronics_category, warehouse_1, monkeypatch):
    """Clock fixed at Monday 09:00 Kuwait (before the 14:00 cut-off).
    Widget has 10 kg and Gadget 5 kg in stock."""
    monkeypatch.setattr(working_calendar_service, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr(quotations_api, "now_jdk", lambda: MONDAY_9AM_KUWAIT)

    team = Team(organisation_id=organisation.id, name="Sales", code="SALES", is_active=True)
    db_session.add(team)
    db_session.commit()
    users = {
        "head": _user(db_session, organisation, "head", MANAGER),
        "a": _user(db_session, organisation, "salesman_a", TEAM_MEMBER),
        "admin": _user(db_session, organisation, "boss", ADMIN),
    }
    db_session.add_all([UserTeam(user_id=users[k].id, team_id=team.id) for k in ("head", "a")])
    gadget = Product(
        organisation_id=organisation.id,
        code="PRD002",
        name="Gadget",
        category_id=electronics_category.id,
        unit_of_measure_id=kilogram_unit.id,
        selling_price=50,
        is_active=True,
    )
    customer = Customer(organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["a"].id)
    db_session.add_all([gadget, customer])
    db_session.commit()
    for reference_id, (product, quantity) in enumerate(((widget_product, "10"), (gadget, "5")), start=1):
        finished_goods_inventory_service.receive_finished_goods(
            db_session,
            organisation_id=organisation.id,
            product_id=product.id,
            warehouse_id=warehouse_1.id,
            quantity=Decimal(quantity),
            unit_of_measure_id=kilogram_unit.id,
            reference_type="test_seed",
            reference_id=reference_id,
            created_by_user_id=None,
        )
    db_session.commit()
    return users, customer, widget_product, gadget, kilogram_unit


def _quote(client, customer, lines, requested=MONDAY):
    body = {
        "customer_id": customer.id,
        "requested_delivery_date": requested.isoformat(),
        "lines": [
            {"product_id": p.id, "quantity": q, "unit_of_measure_id": p.unit_of_measure_id, "unit_price": "100"}
            for p, q in lines
        ],
    }
    response = client.post("/api/quotations", json=body, headers=_headers(client, "salesman_a"))
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def _stock_state(db_session):
    db_session.expire_all()
    return (
        db_session.query(FinishedGoodsMovement).count(),
        sorted((row.product_id, row.quantity_on_hand) for row in db_session.query(FinishedGoodsInventory).all()),
    )


def test_sufficient_fg_is_servable_and_the_check_moves_no_stock(client, db_session, setup):
    users, customer, widget, gadget, unit = setup
    quotation_id = _quote(client, customer, [(widget, "10"), (gadget, "5")])
    before = _stock_state(db_session)

    gate = client.get(f"/api/quotations/{quotation_id}/same-day-fg", headers=_headers(client, "salesman_a")).json()

    assert gate == {"delivery_window": "same_day", "applies": True, "decision": "servable", "shortages": []}
    assert _stock_state(db_session) == before


def test_any_short_line_requires_admin_override(client, setup):
    users, customer, widget, gadget, unit = setup
    headers = _headers(client, "salesman_a")

    # Gadget short (6 > 5) while Widget is fine -> the whole request needs Admin.
    gate = client.get(f"/api/quotations/{_quote(client, customer, [(widget, '10'), (gadget, '6')])}/same-day-fg", headers=headers).json()
    assert gate["decision"] == "admin_override_required"
    assert [(s["product_id"], Decimal(s["requested"]), Decimal(s["available"])) for s in gate["shortages"]] == [
        (gadget.id, Decimal("6"), Decimal("5"))
    ]

    # The same product on two lines is summed: 6 + 6 > 10.
    gate = client.get(f"/api/quotations/{_quote(client, customer, [(widget, '6'), (widget, '6')])}/same-day-fg", headers=headers).json()
    assert gate["decision"] == "admin_override_required"
    assert Decimal(gate["shortages"][0]["requested"]) == Decimal("12")


def test_only_admin_decides_and_can_change_the_decision(client, db_session, setup):
    users, customer, widget, gadget, unit = setup
    quotation_id = _quote(client, customer, [(gadget, "6")])
    url = f"/api/quotations/{quotation_id}/same-day-override"
    before = _stock_state(db_session)

    for username in ("salesman_a", "head"):
        denied = client.put(url, json={"decision": "approved", "reason": "please"}, headers=_headers(client, username))
        assert denied.status_code == 403

    admin = _headers(client, "boss")
    approved = client.put(url, json={"decision": "approved", "reason": "Customer accepts partial stock risk"}, headers=admin)
    assert approved.status_code == 200 and approved.json()["decision"] == "servable"
    rejected = client.put(url, json={"decision": "rejected", "reason": "Reconsidered"}, headers=admin)
    assert rejected.status_code == 200 and rejected.json()["decision"] == "not_servable"

    events = db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_SAME_DAY_OVERRIDE_DECIDED).order_by(AuditEvent.id).all()
    assert [e.actor_user_id for e in events] == [users["admin"].id, users["admin"].id]
    assert "None -> approved" in events[0].details and "approved -> rejected" in events[1].details
    assert _stock_state(db_session) == before


def test_gate_applies_only_to_same_day_requests(client, setup):
    users, customer, widget, gadget, unit = setup
    headers = _headers(client, "salesman_a")

    # Wednesday is within 2 working days: no FG gate, even though Gadget is short.
    wednesday = _quote(client, customer, [(gadget, "99")], requested=date(2026, 9, 30))
    gate = client.get(f"/api/quotations/{wednesday}/same-day-fg", headers=headers).json()
    assert gate == {"delivery_window": "within_2_working_days", "applies": False, "decision": None, "shortages": []}
    # Friday is not a delivery day at all; the calendar decision stands.
    friday = _quote(client, customer, [(gadget, "99")], requested=date(2026, 10, 2))
    assert client.get(f"/api/quotations/{friday}/same-day-fg", headers=headers).json()["delivery_window"] == "not_servable"
    # Nothing to override when the gate doesn't apply.
    override = client.put(
        f"/api/quotations/{wednesday}/same-day-override",
        json={"decision": "approved", "reason": "x"},
        headers=_headers(client, "boss"),
    )
    assert override.status_code == 409


def test_unit_changed_since_quotation_is_refused_not_converted(client, db_session, organisation, setup):
    users, customer, widget, gadget, unit = setup
    quotation_id = _quote(client, customer, [(gadget, "1")])
    litre = UnitOfMeasure(organisation_id=organisation.id, name="Litre", code="L", is_active=True)
    db_session.add(litre)
    db_session.commit()
    gadget.unit_of_measure_id = litre.id
    db_session.commit()

    response = client.get(f"/api/quotations/{quotation_id}/same-day-fg", headers=_headers(client, "salesman_a"))
    assert response.status_code == 400
