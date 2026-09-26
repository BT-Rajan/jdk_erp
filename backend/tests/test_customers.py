"""Tests for docs/modules/customers.md: the first master-data module with
real ownership/visibility scoping. Covers organisation isolation, the
OWN/TEAM/ALL view-scope resolution (default fallback and explicit
permission-table overrides), create/edit/status/assign authorization,
phone/code uniqueness, and the audit trail for every mutation."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.scopes import ALL, OWN, TEAM
from app.models.audit_event import (
    CUSTOMER_ASSIGNED,
    CUSTOMER_CREATED,
    CUSTOMER_STATUS_CHANGED,
    CUSTOMER_UPDATED,
    AuditEvent,
)
from app.models.customer import Customer
from app.models.role_permission import RolePermission
from app.models.user_permission import UserPermission
from app.models.user_team import UserTeam


def _login_headers(client, username, password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _make_customer(db_session, organisation, *, name="Acme Trading", phone=None, assigned_to_user_id=None, code=None):
    import random

    customer = Customer(
        organisation_id=organisation.id,
        code=code or f"CUS{random.randint(10000, 99999)}",
        name=name,
        phone=phone,
        assigned_to_user_id=assigned_to_user_id,
        is_active=True,
    )
    db_session.add(customer)
    db_session.commit()
    db_session.refresh(customer)
    return customer


# --- authentication / organisation isolation --------------------------


def test_list_customers_requires_authentication(client, active_user):
    response = client.get("/api/customers")
    assert response.status_code == 401


def test_list_customers_returns_only_my_organisation(client, admin_user, db_session, organisation, other_organisation):
    mine = _make_customer(db_session, organisation, name="Mine")
    _make_customer(db_session, other_organisation, name="Theirs")

    headers = _login_headers(client, "admin_person")
    response = client.get("/api/customers", headers=headers)
    assert response.status_code == 200
    ids = {c["id"] for c in response.json()["data"]}
    assert ids == {mine.id}


def test_get_customer_in_other_organisation_returns_404(client, admin_user, db_session, other_organisation):
    other = _make_customer(db_session, other_organisation, name="Theirs")
    headers = _login_headers(client, "admin_person")
    response = client.get(f"/api/customers/{other.id}", headers=headers)
    assert response.status_code == 404


# --- view scope: default fallback (no explicit permission grant) -------


def test_team_member_defaults_to_own_scope(client, db_session, organisation, active_user):
    """active_user is role=team_member by default. With no explicit
    role_permissions row, docs/modules/permissions.md #4's own default
    table applies: Team Member -> OWN."""
    mine = _make_customer(db_session, organisation, name="Mine", assigned_to_user_id=active_user.id)
    _make_customer(db_session, organisation, name="Someone else's", assigned_to_user_id=None)

    headers = _login_headers(client, "ada")
    response = client.get("/api/customers", headers=headers)
    assert response.status_code == 200
    ids = {c["id"] for c in response.json()["data"]}
    assert ids == {mine.id}


def test_manager_defaults_to_team_scope(client, db_session, organisation, manager_user, active_user, sales_team):
    db_session.add_all([UserTeam(user_id=manager_user.id, team_id=sales_team.id), UserTeam(user_id=active_user.id, team_id=sales_team.id)])
    db_session.commit()

    teammates_customer = _make_customer(db_session, organisation, name="Teammate's", assigned_to_user_id=active_user.id)
    _make_customer(db_session, organisation, name="Stranger's", assigned_to_user_id=None)

    headers = _login_headers(client, "manager_person")
    response = client.get("/api/customers", headers=headers)
    assert response.status_code == 200
    ids = {c["id"] for c in response.json()["data"]}
    assert ids == {teammates_customer.id}


def test_manager_with_no_team_sees_only_own(client, db_session, organisation, manager_user):
    own = _make_customer(db_session, organisation, name="Manager's own", assigned_to_user_id=manager_user.id)
    _make_customer(db_session, organisation, name="Unrelated", assigned_to_user_id=None)

    headers = _login_headers(client, "manager_person")
    response = client.get("/api/customers", headers=headers)
    ids = {c["id"] for c in response.json()["data"]}
    assert ids == {own.id}


def test_admin_sees_all_customers_regardless_of_assignment(client, admin_user, db_session, organisation, active_user):
    _make_customer(db_session, organisation, name="A", assigned_to_user_id=active_user.id)
    _make_customer(db_session, organisation, name="B", assigned_to_user_id=None)

    headers = _login_headers(client, "admin_person")
    response = client.get("/api/customers", headers=headers)
    assert response.json()["pagination"]["total"] == 2


def test_get_customer_out_of_scope_returns_404_not_403(client, db_session, organisation, active_user):
    """docs/audit/CUSTOMERS_AUDIT.md's adopted jdk_clean choice: never
    confirm existence of a record outside the caller's view scope."""
    other_customer = _make_customer(db_session, organisation, name="Not mine", assigned_to_user_id=None)
    headers = _login_headers(client, "ada")
    response = client.get(f"/api/customers/{other_customer.id}", headers=headers)
    assert response.status_code == 404


# --- view scope: explicit permission-table overrides --------------------


def test_admin_can_grant_team_member_all_scope_via_existing_permissions_api(
    client, db_session, organisation, active_user
):
    """Proves real reuse of the existing engine: an explicit
    role_permissions row for module_key=customers overrides the OWN
    default, with no customer-specific authorization code involved."""
    db_session.add(
        RolePermission(organisation_id=organisation.id, role="team_member", module_key="customers", action="view", scope=ALL)
    )
    db_session.commit()
    _make_customer(db_session, organisation, name="Not assigned to ada", assigned_to_user_id=None)
    _make_customer(db_session, organisation, name="Ada's own", assigned_to_user_id=active_user.id)

    headers = _login_headers(client, "ada")
    response = client.get("/api/customers", headers=headers)
    assert response.json()["pagination"]["total"] == 2


def test_user_permission_override_wins_over_role_default(client, db_session, organisation, active_user):
    db_session.add(
        UserPermission(organisation_id=organisation.id, user_id=active_user.id, module_key="customers", action="view", scope=ALL)
    )
    db_session.commit()
    _make_customer(db_session, organisation, name="Unrelated", assigned_to_user_id=None)

    headers = _login_headers(client, "ada")
    response = client.get("/api/customers", headers=headers)
    assert response.json()["pagination"]["total"] == 1


def test_admin_can_restrict_manager_to_own_scope(client, db_session, organisation, manager_user):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role="manager", module_key="customers", action="view", scope=OWN)
    )
    db_session.commit()
    own = _make_customer(db_session, organisation, name="Manager's own", assigned_to_user_id=manager_user.id)
    _make_customer(db_session, organisation, name="Not manager's", assigned_to_user_id=None)

    headers = _login_headers(client, "manager_person")
    response = client.get("/api/customers", headers=headers)
    ids = {c["id"] for c in response.json()["data"]}
    assert ids == {own.id}


# --- create --------------------------------------------------------------


def test_any_authenticated_user_can_create_a_customer(client, active_user):
    headers = _login_headers(client, "ada")
    response = client.post("/api/customers", json={"name": "New Co"}, headers=headers)
    assert response.status_code == 201


def test_team_member_created_customer_is_auto_assigned_to_self(client, active_user, db_session):
    headers = _login_headers(client, "ada")
    response = client.post(
        "/api/customers", json={"name": "New Co", "assigned_to_user_id": 999999}, headers=headers
    )
    assert response.status_code == 201
    # The client-supplied assignee is silently overridden -- a
    # team_member can never assign a customer to someone else.
    assert response.json()["assigned_to_user_id"] == active_user.id


def test_customer_code_is_auto_generated_and_never_client_supplied(client, active_user):
    headers = _login_headers(client, "ada")
    response = client.post("/api/customers", json={"name": "New Co", "code": "HACKED"}, headers=headers)
    assert response.status_code == 201
    assert response.json()["code"] != "HACKED"
    assert response.json()["code"].startswith("3")


def test_manager_can_assign_customer_to_someone_else_at_create(
    client, db_session, organisation, manager_user, active_user, sales_team
):
    # A department head may assign a new customer to a member of a team they head.
    db_session.add_all([UserTeam(user_id=manager_user.id, team_id=sales_team.id), UserTeam(user_id=active_user.id, team_id=sales_team.id)])
    db_session.commit()
    headers = _login_headers(client, "manager_person")
    response = client.post(
        "/api/customers", json={"name": "New Co", "assigned_to_user_id": active_user.id}, headers=headers
    )
    assert response.status_code == 201
    assert response.json()["assigned_to_user_id"] == active_user.id


def test_create_rejects_assignee_from_another_organisation(client, manager_user, other_org_user):
    headers = _login_headers(client, "manager_person")
    response = client.post(
        "/api/customers", json={"name": "New Co", "assigned_to_user_id": other_org_user.id}, headers=headers
    )
    assert response.status_code == 422


def test_create_rejects_inactive_assignee(client, manager_user, inactive_user):
    """The error message says "must be an active user" -- the lookup
    must actually filter on is_active, not just organisation, or a
    deactivated user could still be handed ownership of a new
    customer."""
    headers = _login_headers(client, "manager_person")
    response = client.post(
        "/api/customers", json={"name": "New Co", "assigned_to_user_id": inactive_user.id}, headers=headers
    )
    assert response.status_code == 422


def test_create_rejects_duplicate_phone(client, active_user, db_session, organisation):
    _make_customer(db_session, organisation, name="Existing", phone="96512345678")
    headers = _login_headers(client, "ada")
    response = client.post(
        "/api/customers", json={"name": "New Co", "phone": "+965 1234 5678"}, headers=headers
    )
    assert response.status_code == 409


def test_create_normalizes_phone_to_digits_only(client, active_user):
    headers = _login_headers(client, "ada")
    response = client.post("/api/customers", json={"name": "New Co", "phone": "+965 1234 5678"}, headers=headers)
    assert response.status_code == 201
    assert response.json()["phone"] == "96512345678"


def test_create_rejects_blank_name(client, active_user):
    headers = _login_headers(client, "ada")
    response = client.post("/api/customers", json={"name": "   "}, headers=headers)
    assert response.status_code == 422


def test_customer_created_audit_event_records_actor(client, active_user, db_session):
    headers = _login_headers(client, "ada")
    response = client.post("/api/customers", json={"name": "New Co"}, headers=headers)
    customer_id = response.json()["id"]

    event = db_session.query(AuditEvent).filter(AuditEvent.action == CUSTOMER_CREATED, AuditEvent.entity_id == customer_id).one()
    assert event.actor_user_id == active_user.id


# --- edit (admin only) ----------------------------------------------------


def test_team_member_cannot_edit_customer(client, active_user, db_session, organisation):
    customer = _make_customer(db_session, organisation, name="Existing", assigned_to_user_id=active_user.id)
    headers = _login_headers(client, "ada")
    response = client.patch(f"/api/customers/{customer.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_manager_cannot_edit_customer(client, manager_user, db_session, organisation):
    customer = _make_customer(db_session, organisation, name="Existing")
    headers = _login_headers(client, "manager_person")
    response = client.patch(f"/api/customers/{customer.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_edit_customer(client, admin_user, db_session, organisation):
    customer = _make_customer(db_session, organisation, name="Existing")
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/customers/{customer.id}", json={"name": "Renamed"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"

    event = db_session.query(AuditEvent).filter(AuditEvent.action == CUSTOMER_UPDATED, AuditEvent.entity_id == customer.id).one()
    assert event.actor_user_id == admin_user.id


def test_edit_rejects_duplicate_phone(client, admin_user, db_session, organisation):
    _make_customer(db_session, organisation, name="Other", phone="96511111111")
    target = _make_customer(db_session, organisation, name="Target", phone="96522222222")
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/customers/{target.id}", json={"phone": "96511111111"}, headers=headers)
    assert response.status_code == 409


# --- status change (admin only) -------------------------------------------


def test_team_member_cannot_change_customer_status(client, active_user, db_session, organisation):
    customer = _make_customer(db_session, organisation, name="Existing", assigned_to_user_id=active_user.id)
    headers = _login_headers(client, "ada")
    response = client.patch(f"/api/customers/{customer.id}/status", json={"is_active": False}, headers=headers)
    assert response.status_code == 403


def test_admin_can_deactivate_and_reactivate_customer(client, admin_user, db_session, organisation):
    customer = _make_customer(db_session, organisation, name="Existing")
    headers = _login_headers(client, "admin_person")

    deactivate = client.patch(f"/api/customers/{customer.id}/status", json={"is_active": False}, headers=headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    event = db_session.query(AuditEvent).filter(AuditEvent.action == CUSTOMER_STATUS_CHANGED, AuditEvent.entity_id == customer.id).first()
    assert event is not None

    reactivate = client.patch(f"/api/customers/{customer.id}/status", json={"is_active": True}, headers=headers)
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True


def test_inactive_customer_still_visible_with_include_inactive(client, admin_user, db_session, organisation):
    customer = _make_customer(db_session, organisation, name="Existing")
    headers = _login_headers(client, "admin_person")
    client.patch(f"/api/customers/{customer.id}/status", json={"is_active": False}, headers=headers)

    response = client.get(f"/api/customers/{customer.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False


# --- assign (admin or manager only) ---------------------------------------


def test_team_member_cannot_assign_customer(client, active_user, db_session, organisation):
    customer = _make_customer(db_session, organisation, name="Existing", assigned_to_user_id=active_user.id)
    headers = _login_headers(client, "ada")
    response = client.patch(
        f"/api/customers/{customer.id}/assign", json={"assigned_to_user_id": active_user.id}, headers=headers
    )
    assert response.status_code == 403


def test_manager_can_assign_customer(client, manager_user, active_user, db_session, organisation, sales_team):
    # A department head reassigns within a team they head.
    db_session.add_all([UserTeam(user_id=manager_user.id, team_id=sales_team.id), UserTeam(user_id=active_user.id, team_id=sales_team.id)])
    db_session.commit()
    customer = _make_customer(db_session, organisation, name="Existing", assigned_to_user_id=manager_user.id)
    headers = _login_headers(client, "manager_person")
    response = client.patch(
        f"/api/customers/{customer.id}/assign", json={"assigned_to_user_id": active_user.id}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["assigned_to_user_id"] == active_user.id


def test_admin_can_unassign_customer(client, admin_user, active_user, db_session, organisation):
    customer = _make_customer(db_session, organisation, name="Existing", assigned_to_user_id=active_user.id)
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/customers/{customer.id}/assign", json={"assigned_to_user_id": None}, headers=headers)
    assert response.status_code == 200
    assert response.json()["assigned_to_user_id"] is None

    event = db_session.query(AuditEvent).filter(AuditEvent.action == CUSTOMER_ASSIGNED, AuditEvent.entity_id == customer.id).one()
    assert event.actor_user_id == admin_user.id


def test_assign_rejects_assignee_from_another_organisation(client, admin_user, other_org_user, db_session, organisation):
    customer = _make_customer(db_session, organisation, name="Existing")
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/customers/{customer.id}/assign", json={"assigned_to_user_id": other_org_user.id}, headers=headers
    )
    assert response.status_code == 422


def test_assign_rejects_inactive_assignee(client, admin_user, inactive_user, db_session, organisation):
    """Same fix as create: the lookup must filter on is_active, not
    just organisation membership."""
    customer = _make_customer(db_session, organisation, name="Existing")
    headers = _login_headers(client, "admin_person")
    response = client.patch(
        f"/api/customers/{customer.id}/assign", json={"assigned_to_user_id": inactive_user.id}, headers=headers
    )
    assert response.status_code == 422


# --- uniqueness (DB level) ------------------------------------------------


def test_customer_code_unique_within_organisation(db_session, organisation):
    a = Customer(organisation_id=organisation.id, code="CUS00001", name="A", is_active=True)
    db_session.add(a)
    db_session.commit()

    b = Customer(organisation_id=organisation.id, code="CUS00001", name="B", is_active=True)
    db_session.add(b)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_customer_phone_unique_within_organisation_but_not_across(db_session, organisation, other_organisation):
    a = Customer(organisation_id=organisation.id, code="CUS00001", name="A", phone="96512345678", is_active=True)
    db_session.add(a)
    db_session.commit()

    duplicate = Customer(organisation_id=organisation.id, code="CUS00002", name="B", phone="96512345678", is_active=True)
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    other_org_same_phone = Customer(
        organisation_id=other_organisation.id, code="CUS00001", name="C", phone="96512345678", is_active=True
    )
    db_session.add(other_org_same_phone)
    db_session.commit()  # must not raise -- per-organisation uniqueness only


def test_customer_name_is_not_unique(client, active_user, db_session, organisation):
    """Deliberately not deduplicated -- see app/models/customer.py's
    docstring (external real-world business data, not an internally
    curated label)."""
    _make_customer(db_session, organisation, name="Acme Trading")
    headers = _login_headers(client, "ada")
    response = client.post("/api/customers", json={"name": "Acme Trading"}, headers=headers)
    assert response.status_code == 201
