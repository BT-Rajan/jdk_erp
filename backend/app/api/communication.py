from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.audit_event import COMMUNICATION_MODULE, EMAIL_ACCOUNT_UPDATED
from app.models.user import User
from app.schemas.email_account import (
    EmailAccountOut,
    EmailAccountTestResult,
    EmailAccountUpdateRequest,
    SendTestEmailRequest,
)
from app.services import audit_service, email_account_service, email_service

router = APIRouter(prefix="/api/communication", tags=["communication"])


@router.get("/email/providers")
def list_email_providers(_: User = Depends(require_admin)) -> dict:
    """Preset host/port values per provider, for the frontend's provider
    picker to fill the form with on selection -- see
    email_account_service.PROVIDER_PRESETS."""
    return email_account_service.PROVIDER_PRESETS


@router.get("/email", response_model=EmailAccountOut)
def get_email_account(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> EmailAccountOut:
    """Admin-gated and organisation-scoped, same as every other
    Communication endpoint here -- an organisation with no saved mailbox
    yet gets a lazily-created default row (email_account_service._get_or_create),
    not a 404."""
    return email_account_service.get(db, admin.organisation_id)


@router.put("/email", response_model=EmailAccountOut)
def update_email_account(
    payload: EmailAccountUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> EmailAccountOut:
    result = email_account_service.update(db, admin.organisation_id, payload)
    # One commit for the whole operation -- the saved mailbox and its
    # audit event succeed or fail together
    # (docs/modules/database_transaction_integrity.md #5/#6/#9), same
    # pattern as app/api/users.py's change_user_role.
    audit_service.log_event(
        db,
        action=EMAIL_ACCOUNT_UPDATED,
        module=COMMUNICATION_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="email_account",
        result="success",
        details=f"email_address: {result.email_address or '(empty)'}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return result


@router.post("/email/test", response_model=EmailAccountTestResult)
def test_email_account(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    return email_account_service.test_connection(db, admin.organisation_id)


@router.post("/email/send-test", response_model=EmailAccountTestResult)
def send_test_email(
    payload: SendTestEmailRequest,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Actually sends a real email through the saved mailbox -- proves
    the whole pipeline works end to end, not just that credentials open
    a socket (see test_email_account above for that check)."""
    email_service.send_email(
        db,
        admin.organisation_id,
        payload.to_email,
        subject="JDK ERP test email",
        body=(
            "This is a test email from JDK ERP's Communication -> Email settings. "
            "If you received this, sending is configured correctly."
        ),
    )
    return {"ok": True, "message": f"Test email sent to {payload.to_email}."}
