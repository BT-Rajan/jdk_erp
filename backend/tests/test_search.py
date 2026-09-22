"""Tests for docs/modules/search.md: keyword search on GET /api/users
and GET /api/teams narrows the exact same organisation-scoped query the
plain list already uses. The point of these tests isn't "the LIKE
clause matches" -- it's proving the actual security property: a keyword
matching a real record outside the caller's scope (another
organisation, or an inactive record with include_inactive unset)
returns nothing, exactly as the plain list already would."""
from app.core.security import hash_password
from app.models.team import Team
from app.models.user import User


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- users ---------------------------------------------------------------


def test_user_search_matches_full_name(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/users?q=Lovelace", headers=headers)
    assert response.status_code == 200
    assert {u["username"] for u in response.json()} == {"ada"}


def test_user_search_matches_email(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/users?q=ada@example", headers=headers)
    assert {u["username"] for u in response.json()} == {"ada"}


def test_user_search_is_case_insensitive(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/users?q=LOVELACE", headers=headers)
    assert {u["username"] for u in response.json()} == {"ada"}


def test_user_search_no_match_returns_empty_list(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/users?q=zzz-no-such-user", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_user_search_cannot_see_another_organisations_user(client, active_user, other_org_user):
    """The core anti-leak proof: a keyword matching a real record in
    another organisation returns nothing -- not an error, not a
    partial/filtered result, indistinguishable from no match at all."""
    headers = _login_headers(client)
    response = client.get("/api/users?q=Grace", headers=headers)
    assert response.status_code == 200
    assert response.json() == []


def test_user_search_still_excludes_inactive_by_default(client, active_user, inactive_user):
    headers = _login_headers(client)
    response = client.get("/api/users?q=Inactive", headers=headers)
    assert response.json() == []

    response = client.get("/api/users?q=Inactive&include_inactive=true", headers=headers)
    assert {u["username"] for u in response.json()} == {"inactive_user"}


def test_user_search_treats_percent_as_a_literal_character(client, active_user, db_session):
    tricky = User(
        organisation_id=active_user.organisation_id,
        full_name="50% Off Corp",
        email="fifty@example.com",
        username="fifty",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(tricky)
    db_session.commit()

    headers = _login_headers(client)
    # A literal "%" must not act as a SQL wildcard -- it should match
    # only the row that actually contains "50%", not every row (which
    # an unescaped LIKE '%50%%' would do).
    response = client.get("/api/users?q=50%25", headers=headers)
    assert {u["username"] for u in response.json()} == {"fifty"}


def test_empty_keyword_returns_the_plain_authorized_list(client, active_user):
    headers = _login_headers(client)
    without_q = {u["username"] for u in client.get("/api/users", headers=headers).json()}
    with_blank_q = {u["username"] for u in client.get("/api/users?q=", headers=headers).json()}
    assert without_q == with_blank_q == {"ada"}


def test_user_search_keyword_has_a_length_cap(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/users?q=" + "a" * 101, headers=headers)
    assert response.status_code == 422


def test_user_search_requires_authentication(client):
    response = client.get("/api/users?q=ada")
    assert response.status_code == 401


# --- teams -----------------------------------------------------------------


def test_team_search_matches_name(client, active_user, sales_team):
    headers = _login_headers(client)
    response = client.get("/api/teams?q=sal", headers=headers)
    assert {t["name"] for t in response.json()} == {"Sales"}


def test_team_search_matches_code(client, active_user, sales_team):
    headers = _login_headers(client)
    response = client.get("/api/teams?q=SALES", headers=headers)
    assert {t["id"] for t in response.json()} == {sales_team.id}


def test_team_search_no_match_returns_empty_list(client, active_user, sales_team):
    headers = _login_headers(client)
    response = client.get("/api/teams?q=engineering", headers=headers)
    assert response.json() == []


def test_team_search_cannot_see_another_organisations_team(client, active_user, other_organisation, db_session):
    other_team = Team(organisation_id=other_organisation.id, name="Sales", code="SALES", is_active=True)
    db_session.add(other_team)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/teams?q=sales", headers=headers)
    assert response.json() == []


def test_team_search_still_excludes_inactive_by_default(client, active_user, organisation, db_session):
    inactive_team = Team(organisation_id=organisation.id, name="Retired Team", is_active=False)
    db_session.add(inactive_team)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/teams?q=retired", headers=headers)
    assert response.json() == []

    response = client.get("/api/teams?q=retired&include_inactive=true", headers=headers)
    assert {t["name"] for t in response.json()} == {"Retired Team"}
