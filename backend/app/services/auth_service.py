from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AuthError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.auth_event import AuthEvent, AuthEventType
from app.models.organisation import Organisation
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.schemas.auth import TokenResponse

# One message for every login failure -- wrong password, unknown username
# and a deactivated account all look identical to the caller, so none of
# them can be used to enumerate valid usernames or account state
# (docs/audit/AUTHENTICATION_AUDIT.md #3). The real reason is still
# recorded server-side via _log_event for audit/lockout purposes.
GENERIC_LOGIN_ERROR = "Invalid username or password."
LOCKOUT_ERROR = "Too many failed login attempts. Please try again later."


def _log_event(
    db: Session,
    event_type: AuthEventType,
    *,
    user_id: int | None = None,
    actor_user_id: int | None = None,
    username_attempted: str | None = None,
    ip_address: str | None = None,
    reason: str | None = None,
) -> None:
    db.add(
        AuthEvent(
            event_type=event_type.value,
            user_id=user_id,
            actor_user_id=actor_user_id,
            username_attempted=username_attempted,
            ip_address=ip_address,
            reason=reason,
        )
    )
    db.commit()


def revoke_all_sessions(db: Session, user_id: int) -> None:
    """Force re-login everywhere for this user -- used by password change
    and, per docs/modules/session_security.md #8, by role changes."""
    db.query(RefreshToken).filter(RefreshToken.user_id == user_id, RefreshToken.revoked.is_(False)).update(
        {"revoked": True}
    )


def log_role_changed(db: Session, *, user_id: int, actor_user_id: int, old_role: str, new_role: str) -> None:
    _log_event(
        db,
        AuthEventType.ROLE_CHANGED,
        user_id=user_id,
        actor_user_id=actor_user_id,
        reason=f"{old_role}->{new_role}",
    )


def log_team_membership_changed(
    db: Session, *, event_type: AuthEventType, user_id: int, actor_user_id: int, team_id: int
) -> None:
    _log_event(db, event_type, user_id=user_id, actor_user_id=actor_user_id, reason=f"team_id:{team_id}")


def _issue_tokens(db: Session, user: User) -> TokenResponse:
    access_token = create_access_token(user.id, user.organisation_id)
    refresh_token, jti, expires_at = create_refresh_token(user.id)
    db.add(RefreshToken(jti=jti, user_id=user.id, expires_at=expires_at))
    db.commit()
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


def login(db: Session, username: str, password: str, ip_address: str | None) -> TokenResponse:
    window_start = datetime.utcnow() - timedelta(minutes=settings.LOGIN_LOCKOUT_WINDOW_MINUTES)
    recent_failures = (
        db.query(AuthEvent)
        .filter(
            AuthEvent.event_type == AuthEventType.LOGIN_FAILURE.value,
            AuthEvent.username_attempted == username,
            AuthEvent.created_at >= window_start,
        )
        .count()
    )
    if recent_failures >= settings.LOGIN_LOCKOUT_THRESHOLD:
        _log_event(
            db, AuthEventType.LOGIN_FAILURE, username_attempted=username, ip_address=ip_address, reason="locked_out"
        )
        raise AuthError(LOCKOUT_ERROR)

    user = db.query(User).filter(User.username == username).first()
    # Always run password verification, even when the user doesn't exist,
    # so response time can't be used to distinguish "no such user" from
    # "wrong password" (docs/audit/AUTHENTICATION_AUDIT.md #4).
    password_ok = verify_password(password, user.password_hash if user else None)
    organisation = db.query(Organisation).filter(Organisation.id == user.organisation_id).first() if user else None
    organisation_active = organisation is not None and organisation.is_active

    if user is None or not password_ok or not user.is_active or not organisation_active:
        if user is None:
            reason = "unknown_user"
        elif not password_ok:
            reason = "bad_password"
        elif not user.is_active:
            reason = "inactive"
        else:
            reason = "organisation_inactive"
        _log_event(
            db,
            AuthEventType.LOGIN_FAILURE,
            user_id=user.id if user else None,
            username_attempted=username,
            ip_address=ip_address,
            reason=reason,
        )
        raise AuthError(GENERIC_LOGIN_ERROR)

    user.last_login_at = datetime.utcnow()
    db.add(user)
    _log_event(
        db,
        AuthEventType.LOGIN_SUCCESS,
        user_id=user.id,
        actor_user_id=user.id,
        username_attempted=username,
        ip_address=ip_address,
    )

    return _issue_tokens(db, user)


def refresh(db: Session, refresh_token: str) -> TokenResponse:
    payload = decode_token(refresh_token)
    if payload.get("type") != "refresh":
        raise AuthError("Invalid refresh token.")

    jti = payload.get("jti")
    record = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
    now = datetime.utcnow()
    if record is None or record.revoked or record.expires_at < now:
        raise AuthError("Invalid refresh token.")

    # Idle timeout (docs/modules/session_security.md #5): a session that
    # hasn't been refreshed recently enough is dead, even if it hasn't
    # hit its absolute expiry yet.
    idle_cutoff = now - timedelta(minutes=settings.SESSION_IDLE_TIMEOUT_MINUTES)
    if record.last_used_at < idle_cutoff:
        record.revoked = True
        db.add(record)
        db.commit()
        raise AuthError("Session expired due to inactivity.")

    user = (
        db.query(User)
        .join(Organisation, Organisation.id == User.organisation_id)
        .filter(User.id == int(payload["sub"]), User.is_active.is_(True), Organisation.is_active.is_(True))
        .first()
    )
    if user is None:
        raise AuthError("Invalid refresh token.")

    # Rotation: this token is spent the moment it's used, whether or not
    # the caller keeps the new pair -- a replayed refresh token is always
    # rejected (docs/audit/AUTHENTICATION_AUDIT.md #5).
    record.revoked = True
    db.add(record)
    db.commit()

    return _issue_tokens(db, user)


def logout(db: Session, refresh_token: str) -> None:
    try:
        payload = decode_token(refresh_token)
    except AuthError:
        return  # already invalid/expired -- logout is idempotent either way

    jti = payload.get("jti")
    record = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
    if record is not None:
        record.revoked = True
        db.add(record)

    user_id = int(payload["sub"]) if payload.get("sub") else None
    _log_event(db, AuthEventType.LOGOUT, user_id=user_id, actor_user_id=user_id)


def change_password(db: Session, user: User, current_password: str, new_password: str) -> None:
    if not verify_password(current_password, user.password_hash):
        raise AuthError("Current password is incorrect.")
    if verify_password(new_password, user.password_hash):
        raise AuthError("New password must be different from the current password.")

    user.password_hash = hash_password(new_password)
    db.add(user)

    # Force re-login everywhere -- a changed password should invalidate
    # every session, not just the one that changed it.
    revoke_all_sessions(db, user.id)

    _log_event(db, AuthEventType.PASSWORD_CHANGE, user_id=user.id, actor_user_id=user.id)
