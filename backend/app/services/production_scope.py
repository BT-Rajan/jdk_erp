"""Production authorization (Production P1) -- the same module_key/action/
scope engine (app/services/authorization_service.py) every other module's
scope file uses, not a new permission system. Admin/Super Admin bypass it
the same way.

- `view`: read Production Requirements (demand/shortfall records).
- `manage`: plan, schedule, issue and cancel (and resolve a
  `bom_required` requirement's BOM snapshot).
- `execute`: start Production Orders and record actual production.

Sales-side changes that move a requirement (Admin quantity edits, order
cancellation, delivery) stay under their own existing authority."""

from sqlalchemy.orm import Session

from app.core.errors import AccessDeniedError
from app.core.roles import ADMIN_ROLES
from app.models.user import User
from app.services import authorization_service

MODULE_KEY = "production"
VIEW = "view"
MANAGE = "manage"
# Production Execution (P6): start orders and record actual production --
# shop-floor work, granted independently of planning (`manage`).
EXECUTE = "execute"


def can_perform(db: Session, user: User, action: str) -> bool:
    if user.role in ADMIN_ROLES:
        return True
    return authorization_service.can(db, user, MODULE_KEY, action)


def require_permission(db: Session, user: User, action: str) -> None:
    if not can_perform(db, user, action):
        raise AccessDeniedError("You do not have permission to do this.")
