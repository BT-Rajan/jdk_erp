from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AccessDeniedError, AuthError
from app.core.roles import ADMIN_ROLES
from app.core.security import decode_token
from app.models.organisation import Organisation
from app.models.user import User

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Resolves who the caller is -- nothing more. No role or permission
    lookup happens here on purpose; that's a separate, later dependency
    the RBAC layer adds on top of this one (docs/modules/authentication.md #6).
    Raises AuthError directly -- the global handler
    (docs/modules/api_error_handling.md) turns it into the standard
    envelope, so no per-call try/except is needed here."""
    if credentials is None:
        raise AuthError("Not authenticated.")

    payload = decode_token(credentials.credentials)

    if payload.get("type") != "access":
        raise AuthError("Invalid token type.")

    # Joined so a deactivated organisation (docs/modules/organisation.md #7)
    # blocks every subsequent request, not just new logins -- an
    # already-issued access token stops working on its next use, same as
    # it already does for a deactivated user.
    user = (
        db.query(User)
        .join(Organisation, Organisation.id == User.organisation_id)
        .filter(User.id == int(payload["sub"]), User.is_active.is_(True), Organisation.is_active.is_(True))
        .first()
    )
    if user is None:
        raise AuthError("User not found or inactive.")

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """The RBAC layer's own dependency, composed on top of get_current_user
    rather than fused into it (docs/modules/authentication.md #6). Gates
    team-membership and role-change endpoints
    (docs/modules/roles_rbac.md #4)."""
    if current_user.role not in ADMIN_ROLES:
        raise AccessDeniedError("Admin privileges required.")
    return current_user
