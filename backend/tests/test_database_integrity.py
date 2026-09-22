"""Tests for docs/modules/database_transaction_integrity.md -- foreign
key enforcement/delete behaviour and the login/refresh transaction
atomicity fix in app/services/auth_service.py."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.core.security import decode_token
from app.models.audit_event import LOGIN_SUCCESS, AuditEvent
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.models.user_permission import UserPermission
from app.models.user_team import UserTeam
from app.services import auth_service

PASSWORD = "Str0ng!Pass"


def test_sqlite_enforces_foreign_keys(db_session):
    # The one thing every other test in this file depends on -- without
    # PRAGMA foreign_keys=ON, SQLite silently ignores every FK below
    # (docs/modules/database_transaction_integrity.md #2/#8).
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_deleting_an_organisation_with_users_is_restricted(db_session, organisation, active_user):
    db_session.delete(organisation)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_deleting_a_user_cascades_refresh_tokens_and_memberships(db_session, active_user, sales_team):
    db_session.add(RefreshToken(jti="cascade-test", user_id=active_user.id, expires_at=datetime.utcnow() + timedelta(days=1)))
    db_session.add(UserTeam(user_id=active_user.id, team_id=sales_team.id))
    db_session.add(UserPermission(organisation_id=active_user.organisation_id, user_id=active_user.id, module_key="sales", action="view", scope="OWN"))
    db_session.commit()

    db_session.delete(active_user)
    db_session.commit()

    assert db_session.query(RefreshToken).filter(RefreshToken.jti == "cascade-test").count() == 0
    assert db_session.query(UserTeam).filter(UserTeam.team_id == sales_team.id).count() == 0
    assert db_session.query(UserPermission).filter(UserPermission.module_key == "sales").count() == 0


def test_deleting_a_user_nulls_out_audit_event_references_but_keeps_the_row(db_session, active_user):
    db_session.add(
        AuditEvent(
            action=LOGIN_SUCCESS,
            module="security",
            organisation_id=active_user.organisation_id,
            user_id=active_user.id,
            actor_user_id=active_user.id,
        )
    )
    db_session.commit()

    db_session.delete(active_user)
    db_session.commit()

    event = db_session.query(AuditEvent).filter(AuditEvent.action == LOGIN_SUCCESS).one()
    assert event.user_id is None
    assert event.actor_user_id is None


def test_login_success_is_atomic_with_token_issuance(db_session, active_user, monkeypatch):
    """Before the fix, login() committed last_login_at + the audit event
    in one transaction, then issued the refresh token in a second commit
    -- a failure in the second left a "login succeeded" audit record for
    a login the caller never got tokens for
    (docs/modules/database_transaction_integrity.md #9/#10)."""

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated token-issuance failure")

    monkeypatch.setattr(auth_service, "create_refresh_token", _boom)

    with pytest.raises(RuntimeError):
        auth_service.login(db_session, active_user.username, PASSWORD, None)
    db_session.rollback()

    fresh = SessionLocal()
    try:
        reloaded = fresh.query(User).filter(User.id == active_user.id).one()
        assert reloaded.last_login_at is None
        assert fresh.query(AuditEvent).filter(AuditEvent.action == LOGIN_SUCCESS, AuditEvent.user_id == active_user.id).count() == 0
    finally:
        fresh.close()


def test_refresh_does_not_revoke_the_old_token_if_reissue_fails(db_session, active_user, monkeypatch):
    """Before the fix, refresh() committed the old token's revocation,
    then issued the replacement in a second commit -- a failure there
    burned the caller's only valid session with nothing to replace it
    (docs/modules/database_transaction_integrity.md #5/#9)."""
    tokens = auth_service.login(db_session, active_user.username, PASSWORD, None)
    jti = decode_token(tokens.refresh_token)["jti"]

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated re-issuance failure")

    monkeypatch.setattr(auth_service, "create_refresh_token", _boom)

    with pytest.raises(RuntimeError):
        auth_service.refresh(db_session, tokens.refresh_token)
    db_session.rollback()

    fresh = SessionLocal()
    try:
        record = fresh.query(RefreshToken).filter(RefreshToken.jti == jti).one()
        assert record.revoked is False
    finally:
        fresh.close()
