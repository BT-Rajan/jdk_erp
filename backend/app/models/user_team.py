from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserTeam(Base):
    """The many-to-many membership table docs/modules/roles_rbac.md #1/#5
    calls for, replacing the earlier one-team-per-user users.team_id
    column. A plain join row -- no role or permission data lives here,
    same as Team itself."""

    __tablename__ = "user_teams"
    __table_args__ = (UniqueConstraint("user_id", "team_id", name="uq_user_teams_user_id_team_id"),)

    # CASCADE on both sides: a membership row is a pure join record with
    # no standalone value once either side is gone
    # (docs/modules/database_transaction_integrity.md #2).
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
