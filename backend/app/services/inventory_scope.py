"""Inventory authorization (Controlled Stock Adjustments, Controlled
Opening Stock) -- the same module_key/action/scope engine
(app/services/authorization_service.py) every other module's own scope
file (purchase_scope.py, rfq_scope.py, purchase_payment_scope.py)
already uses, not a new permission system. `module_key="inventory"` is
deliberately its own key, distinct from `purchase` -- a warehouse user's
`purchase:receive` grant (goods receiving) must never, by itself, also
grant the authority to adjust stock or record opening stock (gap-fix:
Controlled Stock Adjustments / Controlled Opening Stock --
authorization). `adjust` and `opening_stock` are deliberately two
separate actions within this one module (not one shared action) so an
organisation can grant them independently -- e.g. a one-time
data-migration grant for opening stock without also granting ongoing
adjustment authority -- while still reusing this exact same scope file,
engine and tables; either (or admin/super_admin, which bypasses every
module's grants the same way every other scope file's own
`can_perform` already does) is required."""

from sqlalchemy.orm import Session

from app.core.errors import AccessDeniedError
from app.core.roles import ADMIN_ROLES
from app.models.user import User
from app.services import authorization_service

MODULE_KEY = "inventory"
ADJUST = "adjust"
OPENING_STOCK = "opening_stock"


def can_perform(db: Session, user: User, action: str) -> bool:
    if user.role in ADMIN_ROLES:
        return True
    return authorization_service.can(db, user, MODULE_KEY, action)


def require_permission(db: Session, user: User, action: str) -> None:
    if not can_perform(db, user, action):
        raise AccessDeniedError("You do not have permission to do this.")
