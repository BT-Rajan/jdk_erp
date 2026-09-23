"""Purchase Order Payment authorization (docs/modules/purchase_orders.md
#34, Revision 3) -- a deliberately separate module_key from `purchase`
(app/services/purchase_scope.py), so an organisation can grant its
Accounts/Finance team the ability to record/cancel payments
independently of Procurement's own create/issue/confirm/receive
permissions -- directly the task's "a finance person should be able to
change payment status" requirement, through the existing
authorization_service engine (its third real module, after `purchase`
and `rfq`), no new access mechanism. Viewing a payment needs no separate
grant -- it's part of the PO record `purchase_scope.VIEW` already gates."""

from sqlalchemy.orm import Session

from app.core.errors import AccessDeniedError
from app.core.roles import ADMIN_ROLES
from app.models.user import User
from app.services import authorization_service

MODULE_KEY = "purchase_payment"
CREATE = "create"
CANCEL = "cancel"


def can_perform(db: Session, user: User, action: str) -> bool:
    if user.role in ADMIN_ROLES:
        return True
    return authorization_service.can(db, user, MODULE_KEY, action)


def require_permission(db: Session, user: User, action: str) -> None:
    if not can_perform(db, user, action):
        raise AccessDeniedError("You do not have permission to do this.")
