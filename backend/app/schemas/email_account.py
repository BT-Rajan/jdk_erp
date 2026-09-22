from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.validation import validate_email_format


class EmailAccountOut(BaseModel):
    """Never `password_encrypted` or any decrypted form of it --
    `has_password` is the one signal the frontend gets that a password
    is saved, mirroring UserOut's own never-expose-the-secret shape
    (app/schemas/user.py)."""

    model_config = ConfigDict(from_attributes=True)

    provider: str
    email_address: str
    display_name: str
    username: str
    has_password: bool
    incoming_protocol: str
    imap_host: str
    imap_port: int
    imap_use_ssl: bool
    pop3_host: str
    pop3_port: int
    pop3_use_ssl: bool
    smtp_host: str
    smtp_port: int
    smtp_use_tls: bool
    is_active: bool
    last_tested_at: datetime | None
    last_test_ok: bool | None
    last_test_error: str | None


class EmailAccountUpdateRequest(BaseModel):
    provider: str = "gmail"
    email_address: str = ""
    display_name: str = ""
    username: str = ""
    # None keeps the previously saved password (nothing here to change);
    # "" explicitly clears it. Distinguishing the two is why this isn't
    # just `password: str = ""`.
    password: str | None = None
    incoming_protocol: str = "imap"
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_use_ssl: bool = True
    pop3_host: str = "pop.gmail.com"
    pop3_port: int = 995
    pop3_use_ssl: bool = True
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_use_tls: bool = True
    is_active: bool = True

    @field_validator("*", mode="before")
    @classmethod
    def _strip_strings(cls, value):
        # Every field here is prone to being copy-pasted -- an app
        # password/host copied from somewhere that displays it with
        # spacing, or a trailing newline, would otherwise be saved
        # verbatim and silently break the connection with no validation
        # error at all.
        return value.strip() if isinstance(value, str) else value

    @field_validator("email_address")
    @classmethod
    def _check_email(cls, value: str) -> str:
        return validate_email_format(value) if value else value

    @field_validator("incoming_protocol")
    @classmethod
    def _check_protocol(cls, value: str) -> str:
        if value not in {"imap", "pop3"}:
            raise ValueError("incoming_protocol must be 'imap' or 'pop3'.")
        return value

    @model_validator(mode="after")
    def _check_encryption_matches_port(self):
        # 993 (IMAP) / 995 (POP3) are IANA implicit-TLS-only ports -- no
        # real mail server accepts a plaintext connection on them, so
        # this combination is never valid, only ever a copy-paste
        # mistake that would otherwise sit unnoticed until "Test
        # connection" fails with a cryptic socket error. Caught here
        # instead, with a message that says exactly what's wrong, for
        # both directions since 143/110 are the unencrypted counterparts
        # and don't expect a TLS handshake either.
        if self.incoming_protocol == "imap":
            if self.imap_port == 993 and not self.imap_use_ssl:
                raise ValueError(
                    "IMAP port 993 is SSL/TLS-only -- enable SSL, or use port 143 for an unencrypted connection."
                )
            if self.imap_port == 143 and self.imap_use_ssl:
                raise ValueError("IMAP port 143 is not an SSL/TLS port -- disable SSL, or use port 993.")
        else:
            if self.pop3_port == 995 and not self.pop3_use_ssl:
                raise ValueError(
                    "POP3 port 995 is SSL/TLS-only -- enable SSL, or use port 110 for an unencrypted connection."
                )
            if self.pop3_port == 110 and self.pop3_use_ssl:
                raise ValueError("POP3 port 110 is not an SSL/TLS port -- disable SSL, or use port 995.")
        return self


class EmailAccountTestResult(BaseModel):
    ok: bool
    message: str


class SendTestEmailRequest(BaseModel):
    to_email: str

    @field_validator("to_email")
    @classmethod
    def _check_to_email(cls, value: str) -> str:
        return validate_email_format(value)
