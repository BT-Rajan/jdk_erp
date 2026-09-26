"""Production authorization (Production P1) -- the same module_key/action/
scope engine (app/services/authorization_service.py) every other module's
scope file uses, not a new permission system. Admin/Super Admin bypass it
the same way.

- `view`: read Production Requirements (demand/shortfall records).
- `manage`: act on them -- today only resolving a `bom_required`
  requirement by snapshotting the product's active BOM.

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


def can_perform(db: Session, user: User, action: str) -> bool:
    if user.role in ADMIN_ROLES:
        return True
    return authorization_service.can(db, user, MODULE_KEY, action)


def require_permission(db: Session, user: User, action: str) -> None:
    if not can_perform(db, user, action):
        raise AccessDeniedError("You do not have permission to do this.")
