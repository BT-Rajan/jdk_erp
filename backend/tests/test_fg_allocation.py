"""Reservation + FG Allocation foundation.

Reservation: the commercial commitment of an accepted quotation, carried
to its Sales Order -- never physical stock. Allocation: a claim on
physical FG for one Sales Order line, made at hand-off from *free* FG
(on hand - open allocations) and afterwards by an authorised user; never
a stock movement. Delivery consumes the order's own claim and may never
take FG claimed by another order."""

from datetime import datetime
from decimal import Decimal

import pytest

from app.api import quotations as quotations_api
from app.api import sales_orders as sales_orders_api
from app.core.errors import ConflictError
from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import FG_ALLOCATED, FG_ALLOCATION_CONSUMED, FG_ALLOCATION_RELEASED, RESERVATION_CREATED, AuditEvent
from app.models.customer import Customer
from app.models.fg_allocation import FgAllocation, SalesReservation
from app.models.finished_goods_inventory import FinishedGoodsInventory, FinishedGoodsMovement
from app.models.inventory import StockMovement
from app.models.production_requirement import ProductionRequirement
from app.models.quotation import Quotation
from app.models.sales_order import SalesOrder
from app.models.user import User
from app.models.user_permission import UserPermission
from app.services import (
    feasibility_record_service,
    fg_allocation_service,
    finished_goods_inventory_service,
    quotation_readiness_service,
    sales_reservation_service,
    working_calendar_service,
)

MONDAY_9AM_KUWAIT = datetime(2026, 9, 28, 9, 0, tzinfo=JDK_TIMEZONE)


def _headers(client, username):
    login = client.post("/api/auth/login", json={"username": username, "password": "Str0ng!Pass"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def setup(client, db_session, organisation, widget_product, warehouse_1, monkeypatch):
    """100 Widgets on hand. `warehouse` may allocate and deliver; `boss` is Admin."""
    for module in (working_calendar_service, quotations_api, sales_orders_api, feasibility_record_service, quotation_readiness_service):
        monkeypatch.setattr(module, "now_jdk", lambda: MONDAY_9AM_KUWAIT)
    monkeypatch.setattr("app.api.delivery_instructions.now_jdk", lambda: MONDAY_9AM_KUWAIT)
    users = {}
    for username, role in (("salesman_a", TEAM_MEMBER), ("boss", ADMIN), ("warehouse", TEAM_MEMBER)):
        users[username] = User(
            organisation_id=organisation.id, role=role, full_name=username.title(), email=f"{username}@example.com",
            username=username, password_hash=hash_password("Str0ng!Pass"), is_active=True,
        )
        db_session.add(users[username])
    db_session.flush()
    for action in ("allocate", "deliver"):
        db_session.add(UserPermission(
            organisation_id=organisation.id, user_id=users["warehouse"].id, module_key="inventory", action=action, scope="all",
        ))
    customers = [
        Customer(
            organisation_id=organisation.id, code=code, name=name, assigned_to_user_id=users["salesman_a"].id,
            phone=phone, address="Shuwaikh", payment_arrangement="after_delivery",
        )
        for code, name, phone in (("300001", "A Co", "96511111111"), ("300002", "B Co", "96522222222"))
    ]
    widget_product.min_selling_price, widget_product.max_selling_price = Decimal("90"), Decimal("110")
    db_session.add_all(customers)
    db_session.commit()
    finished_goods_inventory_service.receive_finished_goods(
        db_session, organisation_id=organisation.id, product_id=widget_product.id, warehouse_id=warehouse_1.id,
        quantity=Decimal("100"), unit_of_measure_id=widget_product.unit_of_measure_id, reference_type="test_seed",
        reference_id=1, created_by_user_id=None,
    )
    db_session.commit()
    return customers, widget_product, warehouse_1


def _accepted(client, customer, product, quantity):
    a = _headers(client, "salesman_a")
    line = {"product_id": product.id, "quantity": quantity, "unit_of_measure_id": product.unit_of_measure_id, "unit_price": "100"}
    quotation = client.post("/api/quotations", json={"customer_id": customer.id, "requested_delivery_date": "2026-10-05", "lines": [line]}, headers=a).json()
    assert client.post(f"/api/quotations/{quotation['id']}/accept", headers=a).status_code == 200
    return quotation


def _order(client, customer, product, quantity):
    quotation = _accepted(client, customer, product, quantity)
    response = client.post(f"/api/quotations/{quotation['id']}/convert", headers=_headers(client, "salesman_a"))
    assert response.status_code == 201, response.json()
    return response.json()


def _position(client, product):
    body = client.get(f"/api/fg-allocations/products/{product.id}", headers=_headers(client, "warehouse")).json()
    return tuple(Decimal(body[k]) for k in ("on_hand_quantity", "allocated_quantity", "free_quantity"))


def _allocate(client, order, quantity, username="warehouse"):
    body = {"sales_order_line_id": order["lines"][0]["id"], "quantity": quantity}
    return client.post("/api/fg-allocations/allocate", json=body, headers=_headers(client, username))


def _release(client, order, reason="Customer asked to hold", quantity=None, username="boss"):
    body = {"sales_order_line_id": order["lines"][0]["id"], "reason": reason}
    if quantity is not None:
        body["quantity"] = quantity
    return client.post("/api/fg-allocations/release", json=body, headers=_headers(client, username))


def _stock_state(db_session):
    db_session.expire_all()
    return (
        [row.quantity_on_hand for row in db_session.query(FinishedGoodsInventory).order_by(FinishedGoodsInventory.id)],
        db_session.query(FinishedGoodsMovement).count(),
        db_session.query(StockMovement).count(),
    )


def _deliver(client, order, quantity):
    wh = _headers(client, "warehouse")
    body = {"sales_order_id": order["id"], "lines": [{"sales_order_line_id": order["lines"][0]["id"], "quantity": quantity}]}
    instruction = client.post("/api/delivery-instructions", json=body, headers=wh).json()
    client.patch(f"/api/delivery-instructions/{instruction['id']}/lines/{instruction['lines'][0]['id']}", json={"pallet_count": 1}, headers=wh)
    return client.post(f"/api/delivery-instructions/{instruction['id']}/fulfil", headers=wh)


def test_accepted_quotation_reserves_commercially_and_the_order_keeps_the_trace(client, db_session, setup):
    (customer, _), widget, _ = setup
    before = _stock_state(db_session)
    quotation = _accepted(client, customer, widget, "30")
    [reservation] = db_session.query(SalesReservation).all()
    assert (reservation.quotation_id, reservation.line_number, reservation.product_id, reservation.quantity, reservation.status) == (
        quotation["id"], 1, widget.id, 30, "active",
    )
    assert reservation.sales_order_id is None
    # Not physical stock: nothing about FG changed, nothing allocated.
    assert _stock_state(db_session) == before and _position(client, widget) == (100, 0, 100)
    assert db_session.query(AuditEvent).filter(AuditEvent.action == RESERVATION_CREATED).count() == 1

    order = client.post(f"/api/quotations/{quotation['id']}/convert", headers=_headers(client, "salesman_a")).json()
    db_session.expire_all()
    reservation = db_session.query(SalesReservation).one()
    assert (reservation.quotation_id, reservation.sales_order_id, reservation.sales_order_line_id, reservation.status) == (
        quotation["id"], order["id"], order["lines"][0]["id"], "active",
    )


def test_releasing_a_quotation_before_conversion_releases_its_reservation(client, db_session, setup):
    """The existing lifecycle cannot reject or cancel an *accepted*
    quotation, so the release operation is exercised at service level."""
    (customer, _), widget, _ = setup
    quotation = _accepted(client, customer, widget, "30")
    before = _stock_state(db_session)
    released = sales_reservation_service.release_for_quotation(db_session, db_session.get(Quotation, quotation["id"]), "customer withdrew")
    db_session.commit()
    reservation = db_session.query(SalesReservation).one()
    assert len(released) == 1 and (reservation.status, reservation.release_reason) == ("released", "customer withdrew")
    assert reservation.released_at is not None
    assert _stock_state(db_session) == before
    assert db_session.query(ProductionRequirement).count() == 0  # no production demand from a release


def test_hand_off_allocates_free_fg_and_two_orders_never_share_it(client, db_session, setup):
    (a, b), widget, _ = setup
    before = _stock_state(db_session)
    order_a = _order(client, a, widget, "60")
    assert _position(client, widget) == (100, 60, 40)
    order_b = _order(client, b, widget, "50")
    # B gets only what A left free; the rest is B's production shortfall.
    assert _position(client, widget) == (100, 100, 0)
    allocations = {r.sales_order_id: r.quantity for r in db_session.query(FgAllocation)}
    assert allocations == {order_a["id"]: 60, order_b["id"]: 40}
    assert Decimal(db_session.query(ProductionRequirement).one().quantity) == 10
    detail = client.get(f"/api/sales-orders/{order_b['id']}", headers=_headers(client, "boss")).json()["lines"][0]
    assert [Decimal(detail[k]) for k in ("quantity", "allocated_quantity", "fulfilled_quantity", "remaining_quantity")] == [50, 40, 0, 50]
    # Nothing is free any more: a further allocation to B is refused.
    refused = _allocate(client, order_b, "1")
    assert refused.status_code == 409 and "free to allocate" in refused.json()["error"]["message"]
    # Allocation never touched physical stock or created a movement.
    assert _stock_state(db_session) == before
    assert db_session.query(AuditEvent).filter(AuditEvent.action == FG_ALLOCATED).count() == 2


def test_allocation_limits_release_and_permissions(client, db_session, setup):
    (a, b), widget, _ = setup
    order_a = _order(client, a, widget, "60")  # 60 allocated at hand-off
    before = _stock_state(db_session)

    # Release: Admin only, reason required; physical stock unchanged.
    assert _release(client, order_a, username="warehouse").status_code == 403
    assert _release(client, order_a, reason="").status_code == 422
    assert _release(client, order_a, quantity="61").status_code == 409
    released = _release(client, order_a, quantity="20").json()
    assert (Decimal(released["allocated_quantity"]), Decimal(released["remaining_quantity"])) == (40, 60)
    assert _position(client, widget) == (100, 40, 60)
    event = db_session.query(AuditEvent).filter(AuditEvent.action == FG_ALLOCATION_RELEASED).one()
    assert event.actor_user_id is not None and event.created_at and "reason: Customer asked to hold" in event.details
    assert "60 -> 40" in event.details
    assert db_session.query(ProductionRequirement).count() == 0  # releasing creates no production demand

    # Allocate again: never above what the line still needs, never without the grant.
    assert _allocate(client, order_a, "21").status_code == 409
    assert _allocate(client, order_a, "5", username="salesman_a").status_code == 403
    assert _allocate(client, order_a, "0").status_code == 422
    assert Decimal(_allocate(client, order_a, "20").json()["allocated_quantity"]) == 60
    # Never above the free FG: 40 free, B needs 50.
    order_b = _order(client, b, widget, "50")  # takes the 40 free at hand-off
    _release(client, order_b, reason="make room")
    assert _position(client, widget) == (100, 60, 40)
    over = _allocate(client, order_b, "41")
    assert over.status_code == 409 and "Only 40" in over.json()["error"]["message"]
    assert _stock_state(db_session) == before


def test_cancelling_an_order_releases_its_allocation_and_reservation(client, db_session, setup):
    (a, _), widget, _ = setup
    order = _order(client, a, widget, "60")
    before = _stock_state(db_session)
    assert client.post(f"/api/sales-orders/{order['id']}/cancel", json={"reason": "Lost"}, headers=_headers(client, "boss")).status_code == 200
    assert _position(client, widget) == (100, 0, 100)
    reservation = db_session.query(SalesReservation).one()
    assert (reservation.status, reservation.release_reason) == ("released", "Sales Order cancelled: Lost")
    assert "Sales Order cancelled: Lost" in db_session.query(AuditEvent).filter(AuditEvent.action == FG_ALLOCATION_RELEASED).one().details
    assert _stock_state(db_session) == before


def test_delivery_consumes_its_own_allocation_and_never_another_orders(client, db_session, setup):
    (a, b), widget, _ = setup
    order_a = _order(client, a, widget, "60")  # 60 claimed
    order_b = _order(client, b, widget, "50")  # 40 claimed (all that was free), 10 to produce
    movements_before = db_session.query(FinishedGoodsMovement).count()

    # B may use its own 40 (nothing is free) -- never A's stock, though 100 are on the shelf.
    refused = _deliver(client, order_b, "45")
    assert refused.status_code == 409 and "allocated to other Sales Orders" in refused.json()["error"]["message"]
    assert db_session.query(FinishedGoodsMovement).count() == movements_before
    assert _position(client, widget) == (100, 100, 0)

    assert _deliver(client, order_b, "25").status_code == 200
    assert _position(client, widget) == (75, 75, 0)  # physical -25; B's claim 40 -> 15
    assert _deliver(client, order_a, "60").status_code == 200
    assert _position(client, widget) == (15, 15, 0)
    db_session.expire_all()
    assert {r.sales_order_id: r.quantity for r in db_session.query(FgAllocation)} == {order_a["id"]: 0, order_b["id"]: 15}
    # Exactly one delivery movement per fulfilled line, with the delivered quantity.
    movements = db_session.query(FinishedGoodsMovement).filter(FinishedGoodsMovement.movement_type == "delivery").order_by(FinishedGoodsMovement.id).all()
    assert [m.quantity for m in movements] == [Decimal("-25"), Decimal("-60")]
    assert db_session.query(AuditEvent).filter(AuditEvent.action == FG_ALLOCATION_CONSUMED).count() == 2
    # The fully delivered order's reservation is fulfilled.
    assert db_session.query(SalesReservation).filter(SalesReservation.sales_order_id == order_a["id"]).one().status == "fulfilled"


def test_the_existing_negative_stock_protection_still_answers(client, db_session, setup):
    (a, _), widget, _ = setup
    order = _order(client, a, widget, "150")  # 100 claimed, 50 short
    response = _deliver(client, order, "120")
    assert response.status_code == 400 and "negative Finished Goods stock" in response.json()["error"]["message"]
    assert _position(client, widget) == (100, 100, 0)


def test_allocation_never_exceeds_stock_even_from_a_stale_claim(client, db_session, setup):
    """Concurrency: every claim increase re-reads under the product's stock
    lock and a final guard refuses a total above physical on hand; the
    table refuses a negative claim. (Row locks themselves only bite on
    MySQL; SQLite runs these one at a time.)"""
    (a, b), widget, _ = setup
    order_a = _order(client, a, widget, "60")
    order_b = _order(client, b, widget, "50")
    # Simulate a racing writer that already claimed 60 more than exists.
    db_session.query(FgAllocation).filter(FgAllocation.sales_order_id == order_b["id"]).update({FgAllocation.quantity: Decimal("100")})
    db_session.commit()
    order = db_session.get(SalesOrder, order_a["id"])
    with pytest.raises(ConflictError):
        fg_allocation_service.allocate(db_session, order, order.lines[0], Decimal("0.0001"), Decimal("0"))
    db_session.rollback()
    with pytest.raises(Exception):
        db_session.query(FgAllocation).filter(FgAllocation.sales_order_id == order_a["id"]).update({FgAllocation.quantity: Decimal("-1")})
        db_session.commit()
    db_session.rollback()


def test_an_admin_edit_of_an_accepted_quotation_moves_its_reservation(client, db_session, setup):
    (customer, _), widget, _ = setup
    quotation = _accepted(client, customer, widget, "30")
    line = {"product_id": widget.id, "quantity": "45", "unit_of_measure_id": widget.unit_of_measure_id, "unit_price": "100"}
    assert client.patch(f"/api/quotations/{quotation['id']}", json={"lines": [line]}, headers=_headers(client, "boss")).status_code == 200
    db_session.expire_all()
    reservation = db_session.query(SalesReservation).one()
    assert (reservation.quantity, reservation.status, reservation.line_number) == (45, "active", 1)
    assert _position(client, widget) == (100, 0, 100)
