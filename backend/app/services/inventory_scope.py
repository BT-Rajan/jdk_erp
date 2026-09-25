"""Inventory authorization (Controlled Stock Adjustments, Controlled
Opening Stock, ledger/balance reconciliation reporting, and -- Finished
Goods Inventory -- viewing the Finished Goods stock position and
posting a Controlled Finished Goods Stock Adjustment) -- the same
module_key/action/scope engine (app/services/authorization_service.py)
every other module's own scope file (purchase_scope.py, rfq_scope.py,
purchase_payment_scope.py) already uses, not a new permission system.
`module_key="inventory"` is deliberately its own key, distinct from
`purchase` -- a warehouse user's `purchase:receive` grant (goods
receiving) must never, by itself, also grant the authority to adjust
stock, record opening stock, or view the reconciliation report
(gap-fix: Controlled Stock Adjustments / Controlled Opening Stock --
authorization). `adjust`, `opening_stock`, `reconcile` and `view` are
deliberately separate actions within this one module (not one shared
action) so an organisation can grant them independently -- e.g. a
one-time data-migration grant for opening stock without also granting
ongoing adjustment authority, or a read-only reconciliation grant for
someone who should see discrepancies but not act on them -- while still
reusing this exact same scope file, engine and tables; any one of them
(or admin/super_admin, which bypasses every module's grants the same
way every other scope file's own `can_perform` already does) is
required for its own endpoint.

`VIEW` is Finished Goods Inventory's own addition (Finished Goods
stock-position/movement-history viewing) -- named and shaped exactly
like every other module's own `view` action (purchase_scope.VIEW,
rfq_scope.VIEW), reusing this same engine and module rather than
standing up a new permission system for Finished Goods; it satisfies
the "must not receive permission to alter stock merely because they can
view it" requirement precisely because it's granted independently of
`adjust` (which a Finished Goods Adjustment also reuses unchanged, the
same "reuse existing RBAC" instruction -- a stock-altering grant for one
half of Inventory has always meant the same grant for the other)."""

from sqlalchemy.orm import Session

from app.core.errors import AccessDeniedError
from app.core.roles import ADMIN_ROLES
from app.models.user import User
from app.services import authorization_service

MODULE_KEY = "inventory"
ADJUST = "adjust"
OPENING_STOCK = "opening_stock"
RECONCILE = "reconcile"
VIEW = "view"


def can_perform(db: Session, user: User, action: str) -> bool:
    if user.role in ADMIN_ROLES:
        return True
    return authorization_service.can(db, user, MODULE_KEY, action)


def require_permission(db: Session, user: User, action: str) -> None:
    if not can_perform(db, user, action):
        raise AccessDeniedError("You do not have permission to do this.")
