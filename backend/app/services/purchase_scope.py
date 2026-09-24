"""Purchase Order authorization (docs/modules/purchase_orders.md #13) --
the first real caller of app/services/authorization_service.py's
module_key/action/scope engine (docs/modules/permissions.md), which was
built in Phase 1 with no concrete resource to enforce yet. Unlike
app/services/customer_scope.py, no OWN/TEAM scope is resolved here --
jdk_clean's own real Purchase Order design has zero ownership/assignment
dimension on a PO (docs/audit/PROCUREMENT_AUDIT.md #11), so inventing one
now would be speculative. Each action is a plain granted/not-granted
check: admin/super_admin always bypass (the same unconditional exemption
every other admin-gated mutation in this app already uses); everyone else
needs an explicit role_permissions/user_permissions grant for
module_key="purchase" -- no grant means deny, exactly
docs/modules/permissions.md's own documented semantics."""

from sqlalchemy.orm import Session

from app.core.errors import AccessDeniedError
from app.core.roles import ADMIN_ROLES
from app.models.user import User
from app.services import authorization_service

MODULE_KEY = "purchase"
VIEW = "view"
CREATE = "create"
ISSUE = "issue"
APPROVE = "approve"
SEND = "send"
RECEIVE = "receive"


def can_perform(db: Session, user: User, action: str) -> bool:
    if user.role in ADMIN_ROLES:
        return True
    return authorization_service.can(db, user, MODULE_KEY, action)


def require_permission(db: Session, user: User, action: str) -> None:
    if not can_perform(db, user, action):
        raise AccessDeniedError("You do not have permission to do this.")
