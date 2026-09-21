from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.organisation import Organisation
from app.models.user import User
from app.schemas.organisation import OrganisationOut

router = APIRouter(prefix="/api/organisations", tags=["organisations"])


@router.get("/me", response_model=OrganisationOut)
def my_organisation(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Organisation:
    """The one place "which organisation am I in" is available to the
    application (docs/modules/organisation.md #7/#10). Read-only, and
    scoped to the caller's own organisation -- there is no admin API yet
    to create/edit organisations; see docs/audit/ORGANISATION_AUDIT.md."""
    return db.query(Organisation).filter(Organisation.id == current_user.organisation_id).one()
