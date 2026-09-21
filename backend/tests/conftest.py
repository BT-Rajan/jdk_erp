import os
import tempfile
from pathlib import Path

# Must happen before any `app.*` module is imported -- pydantic-settings
# reads the environment once, at import time.
_TMP_DB = Path(tempfile.gettempdir()) / "jdk_erp_test_auth.db"
_TMP_DB.unlink(missing_ok=True)

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-only-for-automated-tests")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TMP_DB}")
os.environ.setdefault("LOGIN_LOCKOUT_THRESHOLD", "3")
os.environ.setdefault("LOGIN_LOCKOUT_WINDOW_MINUTES", "15")

import pytest
from fastapi.testclient import TestClient

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.main import app
from app.models.organisation import Organisation
from app.models.user import User


@pytest.fixture(autouse=True)
def _clean_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def organisation(db_session):
    org = Organisation(name="Test Org", code="TESTORG", currency="USD", timezone="UTC", is_active=True)
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture()
def inactive_organisation(db_session):
    org = Organisation(name="Inactive Org", code="INACTIVEORG", currency="USD", timezone="UTC", is_active=False)
    db_session.add(org)
    db_session.commit()
    db_session.refresh(org)
    return org


@pytest.fixture()
def user_in_inactive_organisation(db_session, inactive_organisation):
    user = User(
        organisation_id=inactive_organisation.id,
        full_name="Org Suspended Person",
        email="suspended-org@example.com",
        username="suspended_org_user",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def active_user(db_session, organisation):
    user = User(
        organisation_id=organisation.id,
        full_name="Ada Lovelace",
        email="ada@example.com",
        username="ada",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def inactive_user(db_session, organisation):
    user = User(
        organisation_id=organisation.id,
        full_name="Inactive Person",
        email="inactive@example.com",
        username="inactive_user",
        password_hash=hash_password("Str0ng!Pass"),
        is_active=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user
