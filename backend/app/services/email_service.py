"""Sends mail through the calling organisation's saved mailbox
(email_account_service.get_smtp_credentials) -- the one place any future
module (quotations, orders, ...) sends an email from, rather than each
rolling its own SMTP code (docs/ENGINEERING_PRINCIPLES.md #2 -- one
reusable implementation for common functionality). Uses only the
standard library (smtplib/email), same dependency-light approach as
app/core/storage.py's LocalStorageBackend -- no new package needed for
something this standard.
"""

import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid

from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ValidationError
from app.services import email_account_service


def is_configured(db: Session, organisation_id: int) -> bool:
    return email_account_service.get_smtp_credentials(db, organisation_id) is not None


def send_email(
    db: Session,
    organisation_id: int,
    to_email: str,
    subject: str,
    body: str,
    attachment_bytes: bytes | None = None,
    attachment_filename: str | None = None,
) -> None:
    """Sends a plain-text email, optionally with a single attachment
    (e.g. a generated PDF). Raises BusinessRuleError with a clear,
    user-facing message on any failure -- an unconfigured mailbox, a bad
    recipient address, or an SMTP-level failure all surface the same way
    to the API layer, which is what lets the frontend just show the
    message directly rather than special-casing each failure mode."""
    config = email_account_service.get_smtp_credentials(db, organisation_id)
    if config is None:
        raise BusinessRuleError(
            "Email isn't configured for this organisation yet. Save a mailbox "
            "with a password under Communication -> Email."
        )
    if not to_email or "@" not in to_email:
        raise ValidationError("Enter a valid recipient email address.")

    from_display = (
        f"{config['from_name']} <{config['from_email']}>"
        if config["from_name"]
        else config["from_email"] or config["username"]
    )

    message = MIMEMultipart()
    message["From"] = from_display
    message["To"] = to_email
    message["Subject"] = subject
    # Both are required by RFC 5322 and their absence is a common,
    # easy-to-miss reason a receiving mail server spam-scores or
    # silently drops an otherwise legitimate message.
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid(domain=config["from_email"].rsplit("@", 1)[-1] or None)
    message.attach(MIMEText(body, "plain"))

    if attachment_bytes is not None:
        # _subtype defaults to "octet-stream" (generic/unknown binary) --
        # give it a real MIME type instead. A properly-typed attachment
        # reads as less suspicious to spam/malware filters than an
        # untyped binary blob.
        attachment = MIMEApplication(attachment_bytes, _subtype="pdf", Name=attachment_filename)
        attachment["Content-Disposition"] = f'attachment; filename="{attachment_filename}"'
        message.attach(attachment)

    try:
        with smtplib.SMTP(config["host"], config["port"], timeout=15) as server:
            if config["use_tls"]:
                server.starttls()
            if config["username"]:
                server.login(config["username"], config["password"])
            server.sendmail(config["from_email"] or config["username"], [to_email], message.as_string())
    except smtplib.SMTPNotSupportedError as exc:
        # Almost always means AUTH was attempted over a connection the
        # server never upgraded to TLS -- most servers only advertise
        # AUTH after STARTTLS, so this is the standard symptom of
        # Encryption being set to "None" (or the wrong port for it).
        raise BusinessRuleError(
            f"Could not send email: {exc} This usually means the mailbox's SMTP "
            "encryption is set to \"None\" -- set it to STARTTLS (or SSL/TLS, "
            "matching the port) under Communication -> Email and save."
        ) from exc
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        raise BusinessRuleError(f"Could not send email: {exc}") from exc
