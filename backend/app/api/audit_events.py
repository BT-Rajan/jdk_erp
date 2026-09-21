from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.audit_event import AuditEvent
from app.models.user import User
from app.schemas.audit_event import AuditEventOut

router = APIRouter(prefix="/api/audit-events", tags=["audit"])


@router.get("", response_model=list[AuditEventOut])
def list_audit_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    user_id: int | None = Query(None),
    actor_user_id: int | None = Query(None),
    module: str | None = Query(None),
    action: str | None = Query(None),
    entity_type: str | None = Query(None),
    entity_id: int | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AuditEvent]:
    """Admin-gated (docs/modules/audit_trail.md #8 -- Team Member has no
    audit access, Manager's isn't built since nothing requires it yet).
    Always paginated (#10) and always organisation-scoped (#7): an event
    with no resolvable organisation (an unknown-username login failure)
    is excluded here rather than shown to any organisation's admin, since
    it isn't that organisation's event and no system-wide viewer exists
    yet to see it."""
    query = db.query(AuditEvent).filter(AuditEvent.organisation_id == admin.organisation_id)
    if user_id is not None:
        query = query.filter(AuditEvent.user_id == user_id)
    if actor_user_id is not None:
        query = query.filter(AuditEvent.actor_user_id == actor_user_id)
    if module is not None:
        query = query.filter(AuditEvent.module == module)
    if action is not None:
        query = query.filter(AuditEvent.action == action)
    if entity_type is not None:
        query = query.filter(AuditEvent.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(AuditEvent.entity_id == entity_id)
    if date_from is not None:
        query = query.filter(AuditEvent.created_at >= date_from)
    if date_to is not None:
        query = query.filter(AuditEvent.created_at <= date_to)

    return query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).offset(skip).limit(limit).all()
