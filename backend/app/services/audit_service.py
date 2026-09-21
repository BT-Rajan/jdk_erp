from sqlalchemy.orm import Session

from app.models.audit_event import AuditEvent


def log_event(
    db: Session,
    *,
    action: str,
    module: str,
    organisation_id: int | None = None,
    user_id: int | None = None,
    actor_user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    result: str | None = None,
    reason: str | None = None,
    details: str | None = None,
    username_attempted: str | None = None,
    ip_address: str | None = None,
) -> None:
    """The one place any module writes an audit event
    (docs/modules/audit_trail.md #1/#11) -- never construct an
    AuditEvent row directly elsewhere. Deliberately does not commit: the
    caller commits the audit row in the same transaction as the business
    change it records, so the two succeed or fail together
    (docs/modules/audit_trail.md #12)."""
    db.add(
        AuditEvent(
            action=action,
            module=module,
            organisation_id=organisation_id,
            user_id=user_id,
            actor_user_id=actor_user_id,
            entity_type=entity_type,
            entity_id=entity_id,
            result=result,
            reason=reason,
            details=details,
            username_attempted=username_attempted,
            ip_address=ip_address,
        )
    )


def diff_fields(before: dict, after: dict, *, ignored_fields: frozenset[str] = frozenset()) -> dict[str, tuple]:
    """The shared "compute changed fields" helper jdk_clean never
    extracted -- it duplicated this loop across 6+ services instead (see
    docs/audit/AUDIT_TRAIL_AUDIT.md). Returns only the fields that
    actually changed, as {field: (old, new)}, for building an event's
    `details` via format_changes()."""
    changes: dict[str, tuple] = {}
    for key, new_value in after.items():
        if key in ignored_fields:
            continue
        old_value = before.get(key)
        if old_value != new_value:
            changes[key] = (old_value, new_value)
    return changes


def format_changes(changes: dict[str, tuple]) -> str:
    """Renders a changes dict as the compact human-readable lines
    docs/modules/audit_trail.md #5 shows (e.g. "role: manager -> team_member"),
    for the `details` column -- never the whole row, before or after."""
    return "; ".join(f"{field}: {old} -> {new}" for field, (old, new) in changes.items())
