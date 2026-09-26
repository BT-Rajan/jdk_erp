"""Sales S9: quotation readiness -- S5 window, current S8 feasibility
record (S6 same day / S7 0-2 days), and S4 price flags combined into a
server-side readiness result. Readiness is not acceptance."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import QUOTATION_READINESS_ASSESSED, AuditEvent
from app.models.customer import Customer
from app.models.feasibility_check import FeasibilityCheck
from app.models.quotation import Quotation
from app.models.user import User
from app.services import (
    feasibility_record_service,
    finished_goods_inventory_service,
    quotation_readiness_service,
    working_calendar_service,
)

MONDAY = date(2026, 9, 28)
WEDNESDAY = date(2026, 9, 30)
MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


def _user(db_session, organisation, username, role):
    user = User(
        organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
        username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(db_session, organisation, widget_product, warehouse_1, monkeypatch):
    """Clock fixed at Monday 09:00 Kuwait; Widget: 10 in FG, permitted
    price 90-110, no BOM."""
    for module in (working_calendar_service, quotations_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    salesman = _user(db_session, organisation, "salesman_a", TEAM_MEMBER)
    _user(db_session, organisation, "boss", ADMIN)
    customers = [
        Customer(organisation_id=organisation.id, code=f"30000{i}", name=f"Co {i}", assigned_to_user_id=salesman.id)
        for i in (1, 2)
    ]
    db_session.add_all(customers)
    widget_product.min_selling_price = Decimal("90")
    widget_product.max_selling_price = Decimal("110")
    db_session.commit()
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=widget_product.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("10"), unit_of_measure_id=widget_product.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    db_session.commit()
    return customers, widget_product


def _quote(client, customer, product, quantity, requested, price="100"):
    body = {
        "customer_id": customer.id,
        "requested_delivery_date": requested.isoformat(),
        "lines": [{"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": price}],
    }
    response = client.post("/api/quotations", json=body, headers=_headers(client, "salesman_a"))
    assert response.status_code == 201, response.json()
    return response.json()["id"]


def _readiness(client, quotation_id):
    response = client.post(f"/api/quotations/{quotation_id}/readiness", headers=_headers(client, "salesman_a"))
    assert response.status_code == 200, response.json()
    body = response.json()
    return body["status"], body["reason_codes"]


def _check(client, quotation_id):
    return client.post(f"/api/quotations/{quotation_id}/feasibility-checks", headers=_headers(client, "salesman_a")).json()


def _decide(client, quotation_id, check_id, decision):
    response = client.put(
        f"/api/quotations/{quotation_id}/feasibility-checks/{check_id}/decision",
        json={"decision": decision, "reason": "Admin call"},
        headers=_headers(client, "boss"),
    )
    assert response.status_code == 200


def test_same_day_needs_a_current_s6_result(client, db_session, setup):
    customers, widget = setup
    enough = _quote(client, customers[0], widget, "10", MONDAY)
    assert _readiness(client, enough) == ("operational_assessment_required", ["feasibility_required"])
    _check(client, enough)
    assert _readiness(client, enough) == ("ready", [])

    short = _quote(client, customers[0], widget, "12", MONDAY)
    check = _check(client, short)
    assert _readiness(client, short) == ("admin_override_required", ["fg_insufficient"])
    _decide(client, short, check["id"], "approved")
    assert _readiness(client, short) == ("ready", [])
    assert db_session.query(AuditEvent).filter(AuditEvent.action == QUOTATION_READINESS_ASSESSED).count() == 4


def test_within_two_working_days_uses_the_s8_decision(client, setup):
    customers, widget = setup
    quotation_id = _quote(client, customers[0], widget, "30", WEDNESDAY)  # FG short, no BOM
    check = _check(client, quotation_id)
    assert check["calculation_basis"] == "within_2_feasibility/v1"
    assert _readiness(client, quotation_id) == ("admin_override_required", ["bom_missing"])
    _decide(client, quotation_id, check["id"], "rejected")
    assert _readiness(client, quotation_id) == ("not_servable", ["feasibility_rejected"])


def test_more_than_two_days_needs_no_feasibility_and_non_working_dates_stay_put(client, db_session, setup):
    customers, widget = setup
    later = _quote(client, customers[0], widget, "999", date(2026, 10, 5))
    assert _readiness(client, later) == ("ready", [])
    assert db_session.query(FeasibilityCheck).count() == 0

    friday = _quote(client, customers[0], widget, "1", date(2026, 10, 2))
    assert _readiness(client, friday) == ("admin_override_required", ["requested_date_non_working"])
    db_session.expire_all()
    assert db_session.get(Quotation, friday).requested_delivery_date == date(2026, 10, 2)


def test_material_change_after_feasibility_requires_a_fresh_check(client, db_session, setup):
    customers, widget = setup
    quotation_id = _quote(client, customers[0], widget, "5", MONDAY)
    _check(client, quotation_id)
    assert _readiness(client, quotation_id) == ("ready", [])

    # No quotation edit exists yet; simulate a future workflow changing the customer.
    quotation = db_session.get(Quotation, quotation_id)
    quotation.customer_id = customers[1].id
    db_session.commit()
    assert _readiness(client, quotation_id) == ("operational_assessment_required", ["feasibility_stale"])

    _check(client, quotation_id)
    assert _readiness(client, quotation_id) == ("ready", [])


def test_price_outside_range_blocks_ready(client, setup):
    customers, widget = setup
    quotation_id = _quote(client, customers[0], widget, "1", date(2026, 10, 5), price="120")
    status, reasons = _readiness(client, quotation_id)
    assert (status, reasons) == ("commercial_approval_required", ["price_outside_range"])
