"""Tests for the common list contract
(docs/audit/TABLES_FORMS_MODALS_FILTERS_AUDIT.md's list-contract
follow-up): app/core/list_query.py's paginate/apply_sort as a
standalone primitive, plus both of today's real consumers (Users,
Teams) proving the same contract holds identically on two different
endpoints -- the data+pagination envelope, sort-field validation, and
page-size capping a frontend can rely on regardless of which resource
it's listing."""
import pytest

from app.core.errors import ValidationError
from app.core.list_query import apply_sort, paginate
from app.core.security import hash_password
from app.models.team import Team
from app.models.user import User


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- app/core/list_query.py, standalone -----------------------------------


def test_paginate_computes_total_and_total_pages(db_session, organisation):
    for i in range(5):
        db_session.add(Team(organisation_id=organisation.id, name=f"Team {i}", is_active=True))
    db_session.commit()

    query = db_session.query(Team).filter(Team.organisation_id == organisation.id)
    rows, pagination = paginate(query, page=1, page_size=2)

    assert len(rows) == 2
    assert pagination.total == 5
    assert pagination.total_pages == 3
    assert pagination.page == 1
    assert pagination.page_size == 2


def test_paginate_second_page_returns_the_remaining_rows(db_session, organisation):
    for i in range(5):
        db_session.add(Team(organisation_id=organisation.id, name=f"Team {i}", is_active=True))
    db_session.commit()

    query = db_session.query(Team).filter(Team.organisation_id == organisation.id).order_by(Team.id)
    page1_rows, _ = paginate(query, page=1, page_size=2)
    page2_rows, pagination = paginate(query, page=2, page_size=2)

    assert len(page2_rows) == 2
    assert pagination.page == 2
    assert {r.id for r in page1_rows}.isdisjoint({r.id for r in page2_rows})


def test_paginate_beyond_last_page_returns_empty_data_not_an_error(db_session, organisation):
    db_session.add(Team(organisation_id=organisation.id, name="Only Team", is_active=True))
    db_session.commit()

    query = db_session.query(Team).filter(Team.organisation_id == organisation.id)
    rows, pagination = paginate(query, page=99, page_size=10)

    assert rows == []
    assert pagination.total == 1
    assert pagination.total_pages == 1


def test_paginate_empty_result_set(db_session, organisation):
    query = db_session.query(Team).filter(Team.organisation_id == organisation.id)
    rows, pagination = paginate(query, page=1, page_size=10)

    assert rows == []
    assert pagination.total == 0
    assert pagination.total_pages == 0


def test_apply_sort_rejects_an_unapproved_field(db_session, organisation):
    query = db_session.query(Team).filter(Team.organisation_id == organisation.id)
    with pytest.raises(ValidationError, match="Cannot sort by"):
        apply_sort(query, "not_a_real_column", "asc", {"name": Team.name}, default=Team.id)


def test_apply_sort_orders_ascending_and_descending(db_session, organisation):
    db_session.add(Team(organisation_id=organisation.id, name="Beta", is_active=True))
    db_session.add(Team(organisation_id=organisation.id, name="Alpha", is_active=True))
    db_session.commit()

    base = db_session.query(Team).filter(Team.organisation_id == organisation.id)
    ascending = apply_sort(base, "name", "asc", {"name": Team.name}, default=Team.id).all()
    descending = apply_sort(base, "name", "desc", {"name": Team.name}, default=Team.id).all()

    assert [t.name for t in ascending] == ["Alpha", "Beta"]
    assert [t.name for t in descending] == ["Beta", "Alpha"]


def test_apply_sort_with_no_sort_by_uses_the_default(db_session, organisation):
    first = Team(organisation_id=organisation.id, name="Zeta", is_active=True)
    second = Team(organisation_id=organisation.id, name="Alpha", is_active=True)
    db_session.add_all([first, second])
    db_session.commit()

    base = db_session.query(Team).filter(Team.organisation_id == organisation.id)
    rows = apply_sort(base, None, "asc", {"name": Team.name}, default=Team.id).all()

    assert [t.id for t in rows] == [first.id, second.id]


# --- endpoint level: the same contract on two real, unrelated resources ---


def test_users_list_supports_pagination(client, active_user, db_session):
    for i in range(3):
        db_session.add(
            User(
                organisation_id=active_user.organisation_id,
                full_name=f"Extra {i}",
                email=f"extra{i}@example.com",
                username=f"extra{i}",
                password_hash=hash_password("Str0ng!Pass"),
                is_active=True,
            )
        )
    db_session.commit()  # ada + 3 extras = 4 users total

    headers = _login_headers(client)
    page1 = client.get("/api/users?page=1&page_size=2", headers=headers).json()
    assert len(page1["data"]) == 2
    assert page1["pagination"] == {"page": 1, "page_size": 2, "total": 4, "total_pages": 2}

    page2 = client.get("/api/users?page=2&page_size=2", headers=headers).json()
    assert len(page2["data"]) == 2

    seen_ids = {u["id"] for u in page1["data"]} | {u["id"] for u in page2["data"]}
    assert len(seen_ids) == 4


def test_users_list_sort_ascending_and_descending(client, active_user, db_session):
    db_session.add(
        User(
            organisation_id=active_user.organisation_id,
            full_name="Zed Zephyr",
            email="zed@example.com",
            username="zed",
            password_hash=hash_password("Str0ng!Pass"),
            is_active=True,
        )
    )
    db_session.commit()

    headers = _login_headers(client)
    asc_names = [u["full_name"] for u in client.get("/api/users?sort_by=full_name&sort_direction=asc", headers=headers).json()["data"]]
    desc_names = [u["full_name"] for u in client.get("/api/users?sort_by=full_name&sort_direction=desc", headers=headers).json()["data"]]

    assert asc_names == sorted(asc_names)
    assert desc_names == sorted(desc_names, reverse=True)
    assert asc_names != desc_names  # proves direction actually flips, not a no-op


def test_users_list_rejects_an_unapproved_sort_field(client, active_user):
    """The security-relevant case: a client can never make this
    endpoint order by an arbitrary column (e.g. password_hash) -- only
    the fixed, reviewed set in app/api/users.py's _SORT_FIELDS."""
    headers = _login_headers(client)
    response = client.get("/api/users?sort_by=password_hash", headers=headers)
    assert response.status_code == 422


def test_users_list_rejects_excessive_page_size(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/users?page_size=1000", headers=headers)
    assert response.status_code == 422


def test_users_list_rejects_page_below_one(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/users?page=0", headers=headers)
    assert response.status_code == 422


def test_users_list_search_filter_and_sort_together(client, active_user, inactive_user, db_session):
    """Proves the three don't fight each other -- q narrows,
    include_inactive widens the active-only default, sort orders the
    combined result, all in the same request."""
    db_session.add(
        User(
            organisation_id=active_user.organisation_id,
            full_name="Zed Example",
            email="zed3@example.com",
            username="zed3",
            password_hash=hash_password("Str0ng!Pass"),
            is_active=True,
        )
    )
    db_session.commit()

    headers = _login_headers(client)
    response = client.get(
        "/api/users?q=example&include_inactive=true&sort_by=full_name&sort_direction=asc", headers=headers
    )
    names = [u["full_name"] for u in response.json()["data"]]

    assert names == sorted(names)
    assert "Zed Example" in names
    assert "Inactive Person" in names  # only present because include_inactive=true


def test_teams_list_supports_pagination_and_sort(client, active_user, organisation, db_session):
    for name in ["Zeta", "Alpha", "Mid"]:
        db_session.add(Team(organisation_id=organisation.id, name=name, is_active=True))
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/teams?sort_by=name&sort_direction=asc&page_size=2", headers=headers)
    body = response.json()

    assert [t["name"] for t in body["data"]] == ["Alpha", "Mid"]
    assert body["pagination"] == {"page": 1, "page_size": 2, "total": 3, "total_pages": 2}


def test_teams_list_rejects_an_unapproved_sort_field(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/teams?sort_by=is_active", headers=headers)
    assert response.status_code == 422


def test_teams_list_rejects_excessive_page_size(client, active_user):
    headers = _login_headers(client)
    response = client.get("/api/teams?page_size=1000", headers=headers)
    assert response.status_code == 422
