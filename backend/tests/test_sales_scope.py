"""Sales S2: Sales access follows Customer ownership
(app/services/customer_scope.py) -- Salesman OWN, Department Head TEAM,
Admin ALL -- and only a Department Head (a manager of a team shared by
the old and new owner) or an admin may reassign a customer."""

import pytest

from app.core.errors import NotFoundError
from app.core.roles import ADMIN, MANAGER, TEAM_MEMBER
from app.core.security import hash_password
from app.models.audit_event import CUSTOMER_ASSIGNED, CUSTOMER_CREATED, AuditEvent
from app.models.customer import Customer
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam
from app.services import customer_scope


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
def sales(db_session, organisation):
    """Sales team: head + salesmen A and B, one customer each, plus an
    admin, a salesman on another team, and an unassigned customer."""
    team = Team(organisation_id=organisation.id, name="Sales", code="SALES", is_active=True)
    other_team = Team(organisation_id=organisation.id, name="Accounts", code="ACC", is_active=True)
    db_session.add_all([team, other_team])
    db_session.commit()
    users = {
        "head": _user(db_session, organisation, "head", MANAGER),
        "a": _user(db_session, organisation, "salesman_a", TEAM_MEMBER),
        "b": _user(db_session, organisation, "salesman_b", TEAM_MEMBER),
        "outsider": _user(db_session, organisation, "outsider", TEAM_MEMBER),
        "admin": _user(db_session, organisation, "boss", ADMIN),
    }
    db_session.add_all(
        [UserTeam(user_id=users[k].id, team_id=team.id) for k in ("head", "a", "b")]
        + [UserTeam(user_id=users["outsider"].id, team_id=other_team.id)]
    )
    customers = {
        "a": Customer(organisation_id=organisation.id, code="300001", name="A Co", assigned_to_user_id=users["a"].id),
        "b": Customer(organisation_id=organisation.id, code="300002", name="B Co", assigned_to_user_id=users["b"].id),
        "outsider": Customer(
            organisation_id=organisation.id, code="300003", name="O Co", assigned_to_user_id=users["outsider"].id
        ),
    }
    db_session.add_all(customers.values())
    db_session.commit()
    return users, customers


def _visible_names(db_session, user):
    query = customer_scope.scope_by_customer(db_session, user, db_session.query(Customer), Customer.id)
    return {c.name for c in query.all()}


def test_sales_scope_matrix_for_lists_and_direct_access(db_session, sales):
    users, customers = sales

    # List filtering: Salesman OWN, Department Head TEAM, Admin ALL.
    assert _visible_names(db_session, users["a"]) == {"A Co"}
    assert _visible_names(db_session, users["head"]) == {"A Co", "B Co"}
    assert _visible_names(db_session, users["admin"]) == {"A Co", "B Co", "O Co"}

    # Direct access (the check a future Sales read/create/update runs on
    # the customer_id it is given): out of scope is the same 404 as missing.
    assert customer_scope.get_accessible_customer(db_session, users["a"], customers["a"].id).name == "A Co"
    for customer_id in (customers["b"].id, customers["outsider"].id, 999999):
        with pytest.raises(NotFoundError):
            customer_scope.get_accessible_customer(db_session, users["a"], customer_id)
    assert customer_scope.get_accessible_customer(db_session, users["head"], customers["b"].id).name == "B Co"


def test_salesman_cannot_reach_or_reassign_another_salesmans_customer_by_id(client, sales):
    users, customers = sales
    headers = _headers(client, "salesman_a")

    assert client.get(f"/api/customers/{customers['a'].id}", headers=headers).status_code == 200
    assert client.get(f"/api/customers/{customers['b'].id}", headers=headers).status_code == 404
    listed = client.get("/api/customers", headers=headers).json()["data"]
    assert [c["name"] for c in listed] == ["A Co"]

    for customer in (customers["a"], customers["b"]):
        response = client.patch(
            f"/api/customers/{customer.id}/assign", json={"assigned_to_user_id": users["a"].id}, headers=headers
        )
        assert response.status_code == 403


def test_department_head_reassignment_moves_future_visibility_not_history(client, db_session, sales):
    users, customers = sales
    customer_id = customers["a"].id
    db_session.add(
        AuditEvent(
            organisation_id=users["a"].organisation_id,
            actor_user_id=users["a"].id,
            action=CUSTOMER_CREATED,
            module="master_data",
            entity_type="customer",
            entity_id=customer_id,
            result="success",
        )
    )
    db_session.commit()

    response = client.patch(
        f"/api/customers/{customer_id}/assign",
        json={"assigned_to_user_id": users["b"].id},
        headers=_headers(client, "head"),
    )
    assert response.status_code == 200

    db_session.expire_all()
    assert _visible_names(db_session, users["a"]) == set()
    assert _visible_names(db_session, users["b"]) == {"A Co", "B Co"}
    created = db_session.query(AuditEvent).filter(AuditEvent.action == CUSTOMER_CREATED).one()
    assert created.actor_user_id == users["a"].id
    assigned = db_session.query(AuditEvent).filter(AuditEvent.action == CUSTOMER_ASSIGNED).one()
    assert assigned.actor_user_id == users["head"].id


def test_department_head_cannot_reassign_outside_own_team_but_admin_can(client, db_session, sales):
    users, customers = sales
    head = _headers(client, "head")

    def assign(headers, customer, assignee):
        return client.patch(
            f"/api/customers/{customer.id}/assign", json={"assigned_to_user_id": assignee}, headers=headers
        ).status_code

    # Another department's customer is not even visible to this head.
    assert assign(head, customers["outsider"], users["a"].id) == 404
    # A team customer cannot be moved to someone outside the team, or un-assigned.
    assert assign(head, customers["a"], users["outsider"].id) == 403
    assert assign(head, customers["a"], None) == 403
    # Nor can a new customer be handed to someone outside the team.
    created = client.post(
        "/api/customers", json={"name": "New Co", "assigned_to_user_id": users["outsider"].id}, headers=head
    )
    assert created.status_code == 403

    db_session.expire_all()
    assert db_session.get(Customer, customers["a"].id).assigned_to_user_id == users["a"].id

    # Admin keeps organisation-wide authority.
    assert assign(_headers(client, "boss"), customers["outsider"], users["a"].id) == 200
