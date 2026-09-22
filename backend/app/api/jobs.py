from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.models.user import User
from app.schemas.job import JobStatsOut
from app.services import job_service

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/stats", response_model=JobStatsOut)
def job_stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> JobStatsOut:
    """Admin-gated, not organisation-scoped -- the jobs table can hold
    system-level jobs with no organisation_id at all
    (docs/modules/background_jobs.md #11), so this is an operational
    view of the whole worker, not a per-tenant one."""
    return JobStatsOut(**job_service.get_job_stats(db))
