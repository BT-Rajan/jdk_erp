"""Tests for docs/modules/roles_rbac.md: admin-gated team membership and
role change, the organisation boundary on both, and the user_teams
uniqueness constraint."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.roles import ADMIN, TEAM_MEMBER
from app.core.security import hash_password
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam


@pytest.fixture()
def admin_user(db_session, organisation):
    user = User(
        organisation_id=organisation.id,
        role=ADMIN,
        full_name="Admin Person",
        email="admin@example.com",
        username="admin_person",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def other_org_team(db_session, other_organisation):
    team = Team(organisation_id=other_organisation.id, name="Sales", is_active=True)
    db_session.add(team)
    db_session.commit()
    db_session.refresh(team)
    return team


def _headers(client, username, password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- team membership: adding a member --------------------------------------


def test_non_admin_cannot_add_team_member(client, active_user, sales_team):
    """active_user defaults to team_member -- docs/modules/roles_rbac.md #4:
    a user cannot add themselves (or anyone) to a team."""
    headers = _headers(client, "ada")
    response = client.post(f"/api/teams/{sales_team.id}/members", json={"user_id": active_user.id}, headers=headers)
    assert response.status_code == 403


def test_admin_can_add_team_member(client, admin_user, active_user, sales_team, db_session):
    headers = _headers(client, "admin_person")
    response = client.post(f"/api/teams/{sales_team.id}/members", json={"user_id": active_user.id}, headers=headers)
    assert response.status_code == 204

    membership = (
        db_session.query(UserTeam).filter_by(user_id=active_user.id, team_id=sales_team.id).first()
    )
    assert membership is not None


def test_add_team_member_requires_authentication(client, sales_team, active_user):
    response = client.post(f"/api/teams/{sales_team.id}/members", json={"user_id": active_user.id})
    assert response.status_code == 401


def test_admin_cannot_add_member_to_inactive_team(client, admin_user, active_user, organisation, db_session):
    inactive_team = Team(organisation_id=organisation.id, name="Retired", is_active=False)
    db_session.add(inactive_team)
    db_session.commit()
    db_session.refresh(inactive_team)

    headers = _headers(client, "admin_person")
    response = client.post(
        f"/api/teams/{inactive_team.id}/members", json={"user_id": active_user.id}, headers=headers
    )
    assert response.status_code == 400


def test_admin_cannot_add_duplicate_membership(client, admin_user, active_user, sales_team):
    headers = _headers(client, "admin_person")
    first = client.post(f"/api/teams/{sales_team.id}/members", json={"user_id": active_user.id}, headers=headers)
    assert first.status_code == 204

    duplicate = client.post(f"/api/teams/{sales_team.id}/members", json={"user_id": active_user.id}, headers=headers)
    assert duplicate.status_code == 409


def test_admin_cannot_add_member_to_other_organisations_team(client, admin_user, active_user, other_org_team):
    headers = _headers(client, "admin_person")
    response = client.post(
        f"/api/teams/{other_org_team.id}/members", json={"user_id": active_user.id}, headers=headers
    )
    assert response.status_code == 404


def test_admin_cannot_add_user_from_other_organisation(client, admin_user, sales_team, other_org_user):
    headers = _headers(client, "admin_person")
    response = client.post(
        f"/api/teams/{sales_team.id}/members", json={"user_id": other_org_user.id}, headers=headers
    )
    assert response.status_code == 404


# --- team membership: removing a member -------------------------------------


def test_non_admin_cannot_remove_team_member(client, active_user, sales_team, db_session):
    db_session.add(UserTeam(user_id=active_user.id, team_id=sales_team.id))
    db_session.commit()

    headers = _headers(client, "ada")
    response = client.delete(f"/api/teams/{sales_team.id}/members/{active_user.id}", headers=headers)
    assert response.status_code == 403


def test_admin_can_remove_team_member(client, admin_user, active_user, sales_team, db_session):
    db_session.add(UserTeam(user_id=active_user.id, team_id=sales_team.id))
    db_session.commit()

    headers = _headers(client, "admin_person")
    response = client.delete(f"/api/teams/{sales_team.id}/members/{active_user.id}", headers=headers)
    assert response.status_code == 204

    membership = (
        db_session.query(UserTeam).filter_by(user_id=active_user.id, team_id=sales_team.id).first()
    )
    assert membership is None


def test_removing_nonexistent_membership_returns_404(client, admin_user, active_user, sales_team):
    headers = _headers(client, "admin_person")
    response = client.delete(f"/api/teams/{sales_team.id}/members/{active_user.id}", headers=headers)
    assert response.status_code == 404


# --- role change --------------------------------------------------------


def test_non_admin_cannot_change_role(client, active_user):
    headers = _headers(client, "ada")
    response = client.patch(f"/api/users/{active_user.id}/role", json={"role": "admin"}, headers=headers)
    assert response.status_code == 403


def test_admin_can_change_a_users_role(client, admin_user, active_user, db_session):
    headers = _headers(client, "admin_person")
    response = client.patch(f"/api/users/{active_user.id}/role", json={"role": "manager"}, headers=headers)
    assert response.status_code == 204

    db_session.refresh(active_user)
    assert active_user.role == "manager"


def test_role_change_rejects_invalid_role(client, admin_user, active_user):
    headers = _headers(client, "admin_person")
    response = client.patch(f"/api/users/{active_user.id}/role", json={"role": "superhero"}, headers=headers)
    assert response.status_code == 422


def test_admin_cannot_change_role_of_user_in_other_organisation(client, admin_user, other_org_user):
    headers = _headers(client, "admin_person")
    response = client.patch(f"/api/users/{other_org_user.id}/role", json={"role": "admin"}, headers=headers)
    assert response.status_code == 404


def test_new_user_defaults_to_team_member_role(active_user):
    assert active_user.role == TEAM_MEMBER


# --- database integrity --------------------------------------------------


def test_user_teams_unique_constraint(db_session, active_user, sales_team):
    db_session.add(UserTeam(user_id=active_user.id, team_id=sales_team.id))
    db_session.commit()

    db_session.add(UserTeam(user_id=active_user.id, team_id=sales_team.id))
    with pytest.raises(IntegrityError):
        db_session.commit()
