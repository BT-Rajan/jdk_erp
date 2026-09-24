"""RFQ authorization (docs/modules/rfq.md #15) -- the second real caller
of app/services/authorization_service.py's module_key/action/scope
engine, mirroring app/services/purchase_scope.py's shape exactly: plain
granted/not-granted checks, no OWN/TEAM scope (no evidenced ownership
dimension for an RFQ either, docs/audit/RFQ_AUDIT.md #7), admin/
super_admin always bypass."""

from sqlalchemy.orm import Session

from app.core.errors import AccessDeniedError
from app.core.roles import ADMIN_ROLES
from app.models.user import User
from app.services import authorization_service

MODULE_KEY = "rfq"
VIEW = "view"
CREATE = "create"
ISSUE = "issue"
CAPTURE_RESPONSE = "capture_response"
DECIDE = "decide"
CONVERT = "convert"


def can_perform(db: Session, user: User, action: str) -> bool:
    if user.role in ADMIN_ROLES:
        return True
    return authorization_service.can(db, user, MODULE_KEY, action)


def require_permission(db: Session, user: User, action: str) -> None:
    if not can_perform(db, user, action):
        raise AccessDeniedError("You do not have permission to do this.")
