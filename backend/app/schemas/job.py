from datetime import datetime

from pydantic import BaseModel


class JobStatsOut(BaseModel):
    """What #11 asks to be made visible -- counts plus the two ages that
    actually tell you whether the worker is keeping up (an old oldest-
    pending job means it isn't; a stale last-success means it's stuck)."""

    pending_count: int
    running_count: int
    failed_count: int
    completed_count: int
    oldest_pending_scheduled_at: datetime | None
    last_completed_at: datetime | None
