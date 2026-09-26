"""The JDK Assistant (app/services/assistant_service.py): a read-only chat
for any signed-in user, and the Admin-only setting of its AI API key."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.crypto import encrypt_secret
from app.core.database import get_db
from app.models.audit_event import ASSISTANT_KEY_UPDATED, ORGANISATION_MODULE
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.assistant import (
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantSettingsOut,
    AssistantSettingsUpdateRequest,
)
from app.services import assistant_service, audit_service

router = APIRouter(prefix="/api/assistant", tags=["assistant"])


@router.post("/chat", response_model=AssistantChatResponse)
def chat(
    payload: AssistantChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AssistantChatResponse:
    """Answers one question as the signed-in user. Read-only: nothing is
    written, whatever is asked."""
    try:
        reply = assistant_service.chat(db, current_user, payload.message, [m.model_dump() for m in payload.history])
    except assistant_service.AssistantNotConfigured:
        return AssistantChatResponse(reply=assistant_service.NOT_CONFIGURED)
    finally:
        # Lookups only read; make sure nothing is ever left to commit.
        db.rollback()
    return AssistantChatResponse(reply=reply.text, cached=reply.cached)


def _settings_out(organisation: Organisation) -> AssistantSettingsOut:
    api_key = assistant_service.organisation_api_key(organisation)
    if not api_key:
        return AssistantSettingsOut(configured=False)
    return AssistantSettingsOut(
        configured=True, provider=assistant_service.detect_provider(api_key), key_hint=assistant_service.key_hint(api_key)
    )


@router.get("/settings", response_model=AssistantSettingsOut)
def get_settings(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> AssistantSettingsOut:
    return _settings_out(db.get(Organisation, admin.organisation_id))


@router.put("/settings", response_model=AssistantSettingsOut)
def update_settings(
    payload: AssistantSettingsUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> AssistantSettingsOut:
    """Admin only. Sets (encrypted) or removes the API key; the provider
    follows from the key. Audited without the key."""
    organisation = db.get(Organisation, admin.organisation_id)
    api_key = (payload.api_key or "").strip()
    organisation.ai_api_key_encrypted = encrypt_secret(api_key) if api_key else None
    db.add(organisation)
    audit_service.log_event(
        db,
        action=ASSISTANT_KEY_UPDATED,
        module=ORGANISATION_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="organisation",
        entity_id=organisation.id,
        result="success",
        details=f"provider: {assistant_service.detect_provider(api_key)}" if api_key else "key removed",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    assistant_service.clear_answer_cache()
    return _settings_out(organisation)
