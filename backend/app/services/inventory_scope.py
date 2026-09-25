"""Controlled Stock Adjustment authorization -- the same
module_key/action/scope engine (app/services/authorization_service.py)
every other module's own scope file (purchase_scope.py, rfq_scope.py,
purchase_payment_scope.py) already uses, not a new permission system.
`module_key="inventory"` is deliberately its own key, distinct from
`purchase` -- a warehouse user's `purchase:receive` grant (goods
receiving) must never, by itself, also grant the authority to adjust
stock (gap-fix: Controlled Stock Adjustments -- authorization). Only an
explicit `inventory:adjust` grant (or admin/super_admin, which bypasses
every module's grants the same way every other scope file's own
`can_perform` already does) allows it."""

from sqlalchemy.orm import Session

from app.core.errors import AccessDeniedError
from app.core.roles import ADMIN_ROLES
from app.models.user import User
from app.services import authorization_service

MODULE_KEY = "inventory"
ADJUST = "adjust"


def can_perform(db: Session, user: User, action: str) -> bool:
    if user.role in ADMIN_ROLES:
        return True
    return authorization_service.can(db, user, MODULE_KEY, action)


def require_permission(db: Session, user: User, action: str) -> None:
    if not can_perform(db, user, action):
        raise AccessDeniedError("You do not have permission to do this.")
