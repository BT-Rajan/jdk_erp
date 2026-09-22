from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.mixins import OrganisationScopedMixin, TimestampMixin


class EmailAccount(Base, TimestampMixin, OrganisationScopedMixin):
    """Communication module, email channel: one admin-configured mailbox
    per organisation, used both to test a real IMAP/POP3 connection and
    to send mail via SMTP (app/services/email_service.py). Organisation-
    scoped like every other business table here (docs/modules/organisation.md
    #3) -- each organisation configures and owns its own mailbox, unlike
    a single shared instance-wide account.

    `password_encrypted` is Fernet-encrypted at rest (app/core/crypto.py)
    -- never read or returned as plaintext outside this module's own
    service."""

    __tablename__ = "email_accounts"
    __table_args__ = (UniqueConstraint("organisation_id", name="uq_email_accounts_organisation_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="gmail")
    email_address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    username: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    incoming_protocol: Mapped[str] = mapped_column(String(10), nullable=False, default="imap")
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False, default="imap.gmail.com")
    imap_port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    imap_use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    pop3_host: Mapped[str] = mapped_column(String(255), nullable=False, default="pop.gmail.com")
    pop3_port: Mapped[int] = mapped_column(Integer, nullable=False, default=995)
    pop3_use_ssl: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    smtp_host: Mapped[str] = mapped_column(String(255), nullable=False, default="smtp.gmail.com")
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
