from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RefreshToken(Base):
    """Tracks only the token's identifier (jti), not the token itself, so a
    refresh token can be revoked/rotated server-side even though access
    tokens stay fully stateless. This row is also this project's "session"
    record per docs/modules/session_security.md -- expires_at is its
    absolute timeout, last_used_at (updated on every refresh) is its idle
    timeout."""

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
