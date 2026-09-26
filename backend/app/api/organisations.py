from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.errors import ConflictError, NotFoundError
from app.core.timezone import JDK_TIMEZONE
from app.models.audit_event import (
    HOLIDAY_ADDED,
    HOLIDAY_REMOVED,
    ORGANISATION_MODULE,
    ORGANISATION_STATUS_CHANGED,
    ORGANISATION_UPDATED,
    SAME_DAY_CUTOFF_UPDATED,
)
from app.models.organisation import Organisation
from app.models.organisation_holiday import OrganisationHoliday
from app.models.user import User
from app.schemas.organisation import OrganisationOut, OrganisationStatusChangeRequest, OrganisationUpdateRequest
from app.schemas.working_calendar import (
    HolidayCreateRequest,
    HolidayOut,
    SameDayCutoffUpdateRequest,
    WorkingCalendarOut,
)
from app.services import audit_service
from app.services.working_calendar_service import WORKING_WEEKDAY_NAMES

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


def _working_calendar(db: Session, organisation: Organisation) -> WorkingCalendarOut:
    holidays = (
        db.query(OrganisationHoliday)
        .filter(OrganisationHoliday.organisation_id == organisation.id)
        .order_by(OrganisationHoliday.holiday_date)
        .all()
    )
    return WorkingCalendarOut(
        working_days=list(WORKING_WEEKDAY_NAMES),
        timezone=JDK_TIMEZONE.key,
        same_day_cutoff_time=organisation.same_day_cutoff_time,
        holidays=[HolidayOut.model_validate(holiday) for holiday in holidays],
    )


@router.get("/me/working-calendar", response_model=WorkingCalendarOut)
def my_working_calendar(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> WorkingCalendarOut:
    """The organisation's one working calendar (Sunday-Thursday, Kuwait
    time, the same-day cut-off and holidays) -- read by
    app/services/working_calendar_service.py for every delivery-window
    decision. Read-only for everyone; only the admin-gated routes below
    change it."""
    organisation = db.query(Organisation).filter(Organisation.id == current_user.organisation_id).one()
    return _working_calendar(db, organisation)


@router.put("/me/working-calendar/cutoff", response_model=WorkingCalendarOut)
def update_same_day_cutoff(
    payload: SameDayCutoffUpdateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> WorkingCalendarOut:
    """Admin-only. Its own endpoint rather than a field on PATCH /me, so
    editing the organisation's details can never change it by accident."""
    organisation = db.query(Organisation).filter(Organisation.id == admin.organisation_id).one()
    old_cutoff = organisation.same_day_cutoff_time
    new_cutoff = payload.same_day_cutoff_time
    if old_cutoff != new_cutoff:
        organisation.same_day_cutoff_time = new_cutoff
        db.add(organisation)
        audit_service.log_event(
            db,
            action=SAME_DAY_CUTOFF_UPDATED,
            module=ORGANISATION_MODULE,
            organisation_id=admin.organisation_id,
            actor_user_id=admin.id,
            entity_type="organisation",
            entity_id=organisation.id,
            result="success",
            details=f"same_day_cutoff_time: {old_cutoff.strftime('%H:%M:%S')} -> {new_cutoff.strftime('%H:%M:%S')}",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        db.refresh(organisation)
    return _working_calendar(db, organisation)


@router.post("/me/working-calendar/holidays", response_model=HolidayOut, status_code=status.HTTP_201_CREATED)
def add_holiday(
    payload: HolidayCreateRequest,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> OrganisationHoliday:
    """Admin-only. One holiday per organisation per date -- a repeat is
    a 409, never a silent overwrite of the existing row's description."""
    existing = (
        db.query(OrganisationHoliday.id)
        .filter(
            OrganisationHoliday.organisation_id == admin.organisation_id,
            OrganisationHoliday.holiday_date == payload.holiday_date,
        )
        .first()
    )
    if existing is not None:
        raise ConflictError(f"{payload.holiday_date.isoformat()} is already a holiday.")

    holiday = OrganisationHoliday(
        organisation_id=admin.organisation_id,
        holiday_date=payload.holiday_date,
        description=payload.description,
    )
    db.add(holiday)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"{payload.holiday_date.isoformat()} is already a holiday.") from exc

    audit_service.log_event(
        db,
        action=HOLIDAY_ADDED,
        module=ORGANISATION_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="organisation_holiday",
        entity_id=holiday.id,
        result="success",
        details=f"{payload.holiday_date.isoformat()}: {payload.description}",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(holiday)
    return holiday


@router.delete("/me/working-calendar/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_holiday(
    holiday_id: int,
    request: Request,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Admin-only. Another organisation's holiday id is a plain 404."""
    holiday = (
        db.query(OrganisationHoliday)
        .filter(OrganisationHoliday.id == holiday_id, OrganisationHoliday.organisation_id == admin.organisation_id)
        .first()
    )
    if holiday is None:
        raise NotFoundError("Holiday not found.")

    details = f"{holiday.holiday_date.isoformat()}: {holiday.description}"
    db.delete(holiday)
    audit_service.log_event(
        db,
        action=HOLIDAY_REMOVED,
        module=ORGANISATION_MODULE,
        organisation_id=admin.organisation_id,
        actor_user_id=admin.id,
        entity_type="organisation_holiday",
        entity_id=holiday_id,
        result="success",
        details=details,
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
