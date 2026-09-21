import uuid
from datetime import datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.errors import AuthError

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# A real bcrypt hash of a fixed, unrelated password. Verifying against this
# when the username doesn't exist keeps a failed login's response time
# roughly constant, so a client can't tell "no such user" apart from
# "wrong password" by timing alone (docs/audit/AUTHENTICATION_AUDIT.md #4).
_DUMMY_HASH = _pwd_context.hash("dummy-password-for-constant-time-login")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    return _pwd_context.verify(password, password_hash or _DUMMY_HASH)


def create_access_token(user_id: int, organisation_id: int) -> str:
    """No role/permission claim on purpose -- authentication issues identity
    only; authorization re-reads the live role from the database instead of
    trusting a point-in-time snapshot baked into a bearer token (see
    docs/modules/authentication.md #6 and AUTHENTICATION_AUDIT.md #7)."""
    now = datetime.utcnow()
    payload = {
        "sub": str(user_id),
        "org": organisation_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    now = datetime.utcnow()
    jti = str(uuid.uuid4())
    expires_at = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "jti": jti, "type": "refresh", "iat": now, "exp": expires_at}
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti, expires_at


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise AuthError("Invalid or expired token.") from exc
