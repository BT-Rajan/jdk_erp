from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import ConflictError
from app.models.audit_event import ORGANISATION_MODULE, ORGANISATION_STATUS_CHANGED, ORGANISATION_UPDATED
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.organisation import OrganisationOut, OrganisationStatusChangeRequest, OrganisationUpdateRequest
from app.services import audit_service

router = APIRouter(prefix="/api/organisations", tags=["organisations"])


@router.get("/me", response_model=OrganisationOut)
def my_organisation(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Organisation:
    """The one place "which organisation am I in" is available to the
    application (docs/modules/organisation.md #7/#10). Read-only, and
    scoped to the caller's own organisation."""
    return db.query(Organisation).filter(Organisation.id == current_user.organisation_id).one()


@router.patch("/me", response_model=OrganisationOut)
def update_my_organisation(
    payload: OrganisationUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Organisation:
    """Admin-gated editing of the caller's own organisation
    (docs/modules/organisation.md #6) -- reuses the existing RBAC gate
    rather than a new super_admin-only tier, since super_admin and admin
    are identical within their own organisation today
    (app/core/roles.py). There is no organisation_id in the payload to
    escape scope with -- the row edited is always `admin.organisation_id`."""
    organisation = db.query(Organisation).filter(Organisation.id == admin.organisation_id).one()

    updates = payload.model_dump(exclude_unset=True)
    before = {field: getattr(organisation, field) for field in updates}
    for field, value in updates.items():
        setattr(organisation, field, value)
    db.add(organisation)

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("An organisation with this name or code already exists.") from exc

    changes = audit_service.diff_fields(before, updates)
    if changes:
        audit_service.log_event(
            db,
            action=ORGANISATION_UPDATED,
            module=ORGANISATION_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="organisation",
            entity_id=organisation.id,
            result="success",
            details=audit_service.format_changes(changes),
            ip_address=request.client.host if request.client else None,
        )
    db.commit()
    db.refresh(organisation)
    return organisation


@router.patch("/me/status", response_model=OrganisationOut)
def change_my_organisation_status(
    payload: OrganisationStatusChangeRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> Organisation:
    """Admin-gated activate/deactivate (docs/modules/organisation.md #6/#7).
    Deactivating locks out every user in the organisation, the admin
    making the change included -- that is the entire point of the
    feature (already exercised by
    tests/test_organisation.py::test_deactivating_organisation_kills_an_already_issued_token),
    not a bug to guard against the way a user can't deactivate their own
    account (app/api/users.py's change_user_status).

    Reactivating a deactivated organisation through this same endpoint
    is consequently unreachable in self-service: once inactive, no user
    in it can authenticate at all (get_current_user's join, and
    auth_service.login, both require Organisation.is_active), so nothing
    can carry a valid token into this admin-gated route. That mirrors
    creation being bootstrap-only (scripts/seed_admin.py) rather than a
    gap -- reactivation is an operator action (direct database access)
    until a real cross-organisation Super Admin capability exists
    (app/core/roles.py's ADMIN_ROLES comment), which this pass
    deliberately does not build."""
    organisation = db.query(Organisation).filter(Organisation.id == admin.organisation_id).one()
    organisation.is_active = payload.is_active
    db.add(organisation)

    audit_service.log_event(
        db,
        action=ORGANISATION_STATUS_CHANGED,
        module=ORGANISATION_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="organisation",
        entity_id=organisation.id,
        result="success",
        details=f"is_active: {payload.is_active}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(organisation)
    return organisation
