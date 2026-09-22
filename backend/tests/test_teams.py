"""Tests for docs/modules/teams.md acceptance criteria implemented at this
stage: organisation-scoped teams, per-organisation name/code uniqueness,
and using team_id to view team members via the existing users directory.
Role/RBAC-gated team membership tests live in test_roles_rbac.py."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_password
from app.models.team import Team
from app.models.user import User
from app.models.user_team import UserTeam


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_teams_list_requires_authentication(client, active_user):
    response = client.get("/api/teams")
    assert response.status_code == 401


def test_list_teams_returns_only_my_organisation(client, active_user, sales_team, other_organisation, db_session):
    other_team = Team(organisation_id=other_organisation.id, name="Sales", is_active=True)
    db_session.add(other_team)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/teams", headers=headers)

    assert response.status_code == 200
    team_ids = {t["id"] for t in response.json()["data"]}
    assert team_ids == {sales_team.id}


def test_get_team_in_other_organisation_returns_404(client, active_user, other_organisation, db_session):
    other_team = Team(organisation_id=other_organisation.id, name="Sales", is_active=True)
    db_session.add(other_team)
    db_session.commit()
    db_session.refresh(other_team)

    headers = _login_headers(client)
    response = client.get(f"/api/teams/{other_team.id}", headers=headers)
    assert response.status_code == 404


def test_get_nonexistent_team_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/teams/999999", headers=headers)
    assert response.status_code == 404


def test_list_teams_excludes_inactive_by_default(client, active_user, organisation, db_session):
    inactive_team = Team(organisation_id=organisation.id, name="Retired Team", is_active=False)
    db_session.add(inactive_team)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/teams", headers=headers)
    names = {t["name"] for t in response.json()["data"]}
    assert "Retired Team" not in names

    with_inactive = client.get("/api/teams?include_inactive=true", headers=headers)
    names_with_inactive = {t["name"] for t in with_inactive.json()["data"]}
    assert "Retired Team" in names_with_inactive


def test_team_name_unique_within_organisation_but_not_across(db_session, organisation, other_organisation):
    team_a = Team(organisation_id=organisation.id, name="Sales", is_active=True)
    db_session.add(team_a)
    db_session.commit()

    duplicate_in_same_org = Team(organisation_id=organisation.id, name="Sales", is_active=True)
    db_session.add(duplicate_in_same_org)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    same_name_other_org = Team(organisation_id=other_organisation.id, name="Sales", is_active=True)
    db_session.add(same_name_other_org)
    db_session.commit()  # must not raise -- teams.md #2, per-organisation uniqueness only


def test_team_code_unique_within_organisation_when_provided(db_session, organisation):
    team_a = Team(organisation_id=organisation.id, name="Sales", code="SALES", is_active=True)
    db_session.add(team_a)
    db_session.commit()

    duplicate_code = Team(organisation_id=organisation.id, name="Sales EMEA", code="SALES", is_active=True)
    db_session.add(duplicate_code)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # Multiple teams with no code at all must still be allowed.
    no_code_a = Team(organisation_id=organisation.id, name="No Code A", is_active=True)
    no_code_b = Team(organisation_id=organisation.id, name="No Code B", is_active=True)
    db_session.add_all([no_code_a, no_code_b])
    db_session.commit()  # must not raise


def test_users_endpoint_filters_by_team_id_to_view_team_members(client, db_session, organisation, sales_team):
    ada = User(
        organisation_id=organisation.id,
        full_name="Ada Lovelace",
        email="ada@example.com",
        username="ada",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    bob = User(
        organisation_id=organisation.id,
        full_name="Bob NoTeam",
        email="bob@example.com",
        username="bob",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add_all([ada, bob])
    db_session.flush()
    db_session.add(UserTeam(user_id=ada.id, team_id=sales_team.id))
    db_session.commit()

    headers = _login_headers(client)
    response = client.get(f"/api/users?team_id={sales_team.id}", headers=headers)

    assert response.status_code == 200
    usernames = {u["username"] for u in response.json()["data"]}
    assert usernames == {"ada"}


def test_users_endpoint_team_filter_from_other_organisation_yields_no_leak(
    client, active_user, other_organisation, db_session
):
    other_team = Team(organisation_id=other_organisation.id, name="Sales", is_active=True)
    db_session.add(other_team)
    db_session.commit()
    db_session.refresh(other_team)

    headers = _login_headers(client)
    response = client.get(f"/api/users?team_id={other_team.id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_user_without_team_has_empty_team_ids(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/auth/me", headers=headers)
    assert response.json()["team_ids"] == []


def test_user_can_belong_to_multiple_teams(client, db_session, organisation, sales_team):
    """docs/modules/roles_rbac.md #1 -- the corrected many-to-many model."""
    accounts_team = Team(organisation_id=organisation.id, name="Accounts", is_active=True)
    db_session.add(accounts_team)
    db_session.flush()

    ravi = User(
        organisation_id=organisation.id,
        full_name="Ravi",
        email="ravi@example.com",
        username="ravi",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(ravi)
    db_session.flush()
    db_session.add(UserTeam(user_id=ravi.id, team_id=sales_team.id))
    db_session.add(UserTeam(user_id=ravi.id, team_id=accounts_team.id))
    db_session.commit()

    headers = _login_headers(client, username="ravi")
    response = client.get("/api/auth/me", headers=headers)
    assert sorted(response.json()["team_ids"]) == sorted([sales_team.id, accounts_team.id])
