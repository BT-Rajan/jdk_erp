"""Tests for docs/modules/permissions.md: the authorization_service
functions, the admin-gated permission-management API, and the
organisation boundary and role-based lockouts on both."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.roles import MANAGER
from app.core.security import hash_password
from app.models.role_permission import RolePermission
from app.models.user import User
from app.models.user_permission import UserPermission
from app.models.user_team import UserTeam
from app.services import authorization_service


@pytest.fixture()
def manager_user(db_session, organisation):
    user = User(
        organisation_id=organisation.id,
        role=MANAGER,
        full_name="Manager Person",
        email="manager@example.com",
        username="manager_person",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _headers(client, username, password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- authorization_service: pure logic --------------------------------------


def test_get_effective_scope_returns_none_with_no_grant(db_session, active_user):
    assert authorization_service.get_effective_scope(db_session, active_user, "sales", "view") is None
    assert authorization_service.can(db_session, active_user, "sales", "view") is False


def test_get_effective_scope_uses_role_default(db_session, active_user, organisation):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role="team_member", module_key="sales", action="view", scope="own")
    )
    db_session.commit()

    assert authorization_service.get_effective_scope(db_session, active_user, "sales", "view") == "own"
    assert authorization_service.can(db_session, active_user, "sales", "view") is True


def test_user_override_wins_over_role_default(db_session, active_user, organisation):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role="team_member", module_key="accounts", action="view", scope="own")
    )
    db_session.add(
        UserPermission(
            organisation_id=organisation.id, user_id=active_user.id, module_key="accounts", action="view", scope="team"
        )
    )
    db_session.commit()

    assert authorization_service.get_effective_scope(db_session, active_user, "accounts", "view") == "team"


def test_get_user_team_ids_reflects_multiple_and_removed_memberships(db_session, active_user, organisation, sales_team):
    from app.models.team import Team

    accounts_team = Team(organisation_id=organisation.id, name="Accounts", is_active=True)
    db_session.add(accounts_team)
    db_session.flush()
    db_session.add(UserTeam(user_id=active_user.id, team_id=sales_team.id))
    db_session.add(UserTeam(user_id=active_user.id, team_id=accounts_team.id))
    db_session.commit()

    team_ids = authorization_service.get_user_team_ids(db_session, active_user)
    assert sorted(team_ids) == sorted([sales_team.id, accounts_team.id])

    # docs/modules/permissions.md #13 criterion 4 -- removing a team
    # immediately removes that team's access.
    db_session.query(UserTeam).filter_by(user_id=active_user.id, team_id=sales_team.id).delete()
    db_session.commit()
    assert authorization_service.get_user_team_ids(db_session, active_user) == [accounts_team.id]


# --- role-permission management API -----------------------------------


def test_non_admin_cannot_set_role_permission(client, active_user):
    headers = _headers(client, "ada")
    response = client.put("/api/permissions/roles/team_member/sales/view", json={"scope": "own"}, headers=headers)
    assert response.status_code == 403


def test_manager_cannot_set_role_permission(client, manager_user):
    """docs/modules/permissions.md #9/#13 criterion 10: a Manager cannot
    grant Admin/Super Admin (or any) access -- they aren't an admin at all."""
    headers = _headers(client, "manager_person")
    response = client.put("/api/permissions/roles/admin/sales/view", json={"scope": "all"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_set_and_list_role_permission(client, admin_user, db_session):
    headers = _headers(client, "admin_person")
    response = client.put("/api/permissions/roles/team_member/sales/view", json={"scope": "own"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["scope"] == "own"

    listing = client.get("/api/permissions/roles", headers=headers)
    assert listing.status_code == 200
    assert any(p["role"] == "team_member" and p["module_key"] == "sales" for p in listing.json())


def test_setting_role_permission_twice_upserts_not_duplicates(client, admin_user, db_session, organisation):
    headers = _headers(client, "admin_person")
    client.put("/api/permissions/roles/team_member/sales/view", json={"scope": "own"}, headers=headers)
    response = client.put("/api/permissions/roles/team_member/sales/view", json={"scope": "team"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["scope"] == "team"

    rows = (
        db_session.query(RolePermission)
        .filter_by(organisation_id=organisation.id, role="team_member", module_key="sales", action="view")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].scope == "team"


def test_set_role_permission_rejects_invalid_role(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.put("/api/permissions/roles/superhero/sales/view", json={"scope": "own"}, headers=headers)
    assert response.status_code == 400


def test_set_role_permission_rejects_invalid_scope(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.put("/api/permissions/roles/team_member/sales/view", json={"scope": "everything"}, headers=headers)
    assert response.status_code == 422


def test_set_role_permission_rejects_bad_module_key(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.put("/api/permissions/roles/team_member/Sales/view", json={"scope": "own"}, headers=headers)
    assert response.status_code == 400


def test_delete_role_permission(client, admin_user):
    headers = _headers(client, "admin_person")
    client.put("/api/permissions/roles/team_member/sales/view", json={"scope": "own"}, headers=headers)

    delete_response = client.delete("/api/permissions/roles/team_member/sales/view", headers=headers)
    assert delete_response.status_code == 204

    listing = client.get("/api/permissions/roles", headers=headers)
    assert listing.json() == []


def test_delete_nonexistent_role_permission_returns_404(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.delete("/api/permissions/roles/team_member/sales/view", headers=headers)
    assert response.status_code == 404


def test_role_permissions_are_isolated_per_organisation(client, admin_user, other_organisation, db_session):
    headers = _headers(client, "admin_person")
    client.put("/api/permissions/roles/team_member/sales/view", json={"scope": "own"}, headers=headers)

    other_org_grants = (
        db_session.query(RolePermission).filter(RolePermission.organisation_id == other_organisation.id).all()
    )
    assert other_org_grants == []


# --- user-permission override API ---------------------------------------


def test_non_admin_cannot_set_user_permission(client, active_user):
    headers = _headers(client, "ada")
    response = client.put(
        f"/api/permissions/users/{active_user.id}/sales/view", json={"scope": "team"}, headers=headers
    )
    assert response.status_code == 403


def test_admin_can_set_user_permission_and_it_overrides_role_default(client, admin_user, active_user, organisation, db_session):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role="team_member", module_key="sales", action="view", scope="own")
    )
    db_session.commit()

    headers = _headers(client, "admin_person")
    response = client.put(
        f"/api/permissions/users/{active_user.id}/sales/view", json={"scope": "team"}, headers=headers
    )
    assert response.status_code == 200

    effective = authorization_service.get_effective_scope(db_session, active_user, "sales", "view")
    assert effective == "team"


def test_admin_cannot_set_permission_for_user_in_other_organisation(client, admin_user, other_org_user):
    headers = _headers(client, "admin_person")
    response = client.put(
        f"/api/permissions/users/{other_org_user.id}/sales/view", json={"scope": "all"}, headers=headers
    )
    assert response.status_code == 404


def test_list_user_permissions_scoped_to_organisation(client, admin_user, other_org_user):
    headers = _headers(client, "admin_person")
    response = client.get(f"/api/permissions/users/{other_org_user.id}", headers=headers)
    assert response.status_code == 404


def test_delete_user_permission(client, admin_user, active_user):
    headers = _headers(client, "admin_person")
    client.put(f"/api/permissions/users/{active_user.id}/sales/view", json={"scope": "team"}, headers=headers)

    delete_response = client.delete(f"/api/permissions/users/{active_user.id}/sales/view", headers=headers)
    assert delete_response.status_code == 204

    listing = client.get(f"/api/permissions/users/{active_user.id}", headers=headers)
    assert listing.json() == []


# --- self-service effective-scope check ---------------------------------


def test_my_effective_scope_requires_authentication(client):
    response = client.get("/api/permissions/me?module_key=sales&action=view")
    assert response.status_code == 401


def test_my_effective_scope_null_with_no_grant(client, active_user):
    headers = _headers(client, "ada")
    response = client.get("/api/permissions/me?module_key=sales&action=view", headers=headers)
    assert response.status_code == 200
    assert response.json()["scope"] is None


def test_my_effective_scope_reflects_role_grant(client, admin_user, active_user, organisation, db_session):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role="team_member", module_key="sales", action="view", scope="own")
    )
    db_session.commit()

    headers = _headers(client, "ada")
    response = client.get("/api/permissions/me?module_key=sales&action=view", headers=headers)
    assert response.json()["scope"] == "own"


# --- database integrity --------------------------------------------------


def test_role_permission_unique_constraint(db_session, organisation):
    db_session.add(
        RolePermission(organisation_id=organisation.id, role="team_member", module_key="sales", action="view", scope="own")
    )
    db_session.commit()

    db_session.add(
        RolePermission(organisation_id=organisation.id, role="team_member", module_key="sales", action="view", scope="team")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_user_permission_unique_constraint(db_session, active_user, organisation):
    db_session.add(
        UserPermission(organisation_id=organisation.id, user_id=active_user.id, module_key="sales", action="view", scope="own")
    )
    db_session.commit()

    db_session.add(
        UserPermission(organisation_id=organisation.id, user_id=active_user.id, module_key="sales", action="view", scope="team")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
