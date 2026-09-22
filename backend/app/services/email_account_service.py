"""Communication module, email channel: one admin-configured mailbox per
organisation, used for both testing a real IMAP/POP3 connection and
sending mail (app/services/email_service.py). Ported from jdk_clean's
single shared account to jdk_erp's own conventions: organisation-scoped
like every other business table here (docs/modules/organisation.md #3),
jdk_erp's AppError subclasses instead of jdk_clean's, and
app/core/crypto.py for the same Fernet-encrypt-at-rest approach.
"""

import imaplib
import poplib
import smtplib
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret, encrypt_secret
from app.core.errors import ValidationError
from app.models.email_account import EmailAccount
from app.schemas.email_account import EmailAccountOut, EmailAccountUpdateRequest

# Known-host presets, keyed by provider id -- the frontend's provider
# picker fills the host/port fields on selection; "custom" leaves them
# for the admin to type. Standard published server settings per
# provider, as of this writing.
PROVIDER_PRESETS: dict[str, dict] = {
    "gmail": {
        "label": "Gmail",
        "imap_host": "imap.gmail.com", "imap_port": 993, "imap_use_ssl": True,
        "pop3_host": "pop.gmail.com", "pop3_port": 995, "pop3_use_ssl": True,
        "smtp_host": "smtp.gmail.com", "smtp_port": 587, "smtp_use_tls": True,
        "note": "Use a Google App Password, not your normal login password (requires 2-Step Verification).",
    },
    "outlook": {
        "label": "Outlook / Microsoft 365",
        "imap_host": "outlook.office365.com", "imap_port": 993, "imap_use_ssl": True,
        "pop3_host": "outlook.office365.com", "pop3_port": 995, "pop3_use_ssl": True,
        "smtp_host": "smtp.office365.com", "smtp_port": 587, "smtp_use_tls": True,
        "note": "",
    },
    "yahoo": {
        "label": "Yahoo Mail",
        "imap_host": "imap.mail.yahoo.com", "imap_port": 993, "imap_use_ssl": True,
        "pop3_host": "pop.mail.yahoo.com", "pop3_port": 995, "pop3_use_ssl": True,
        "smtp_host": "smtp.mail.yahoo.com", "smtp_port": 587, "smtp_use_tls": True,
        "note": "Requires a Yahoo App Password.",
    },
    "icloud": {
        "label": "iCloud Mail",
        "imap_host": "imap.mail.me.com", "imap_port": 993, "imap_use_ssl": True,
        "pop3_host": "", "pop3_port": 995, "pop3_use_ssl": True,
        "smtp_host": "smtp.mail.me.com", "smtp_port": 587, "smtp_use_tls": True,
        "note": "iCloud does not support POP3 -- IMAP only.",
    },
    "custom": {
        "label": "Custom / other",
        "imap_host": "", "imap_port": 993, "imap_use_ssl": True,
        "pop3_host": "", "pop3_port": 995, "pop3_use_ssl": True,
        "smtp_host": "", "smtp_port": 587, "smtp_use_tls": True,
        "note": "",
    },
}


def _get_or_create(db: Session, organisation_id: int) -> EmailAccount:
    row = db.query(EmailAccount).filter(EmailAccount.organisation_id == organisation_id).first()
    if row is None:
        preset = PROVIDER_PRESETS["gmail"]
        row = EmailAccount(
            organisation_id=organisation_id,
            provider="gmail",
            imap_host=preset["imap_host"], imap_port=preset["imap_port"], imap_use_ssl=preset["imap_use_ssl"],
            pop3_host=preset["pop3_host"], pop3_port=preset["pop3_port"], pop3_use_ssl=preset["pop3_use_ssl"],
            smtp_host=preset["smtp_host"], smtp_port=preset["smtp_port"], smtp_use_tls=preset["smtp_use_tls"],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _to_out(row: EmailAccount) -> EmailAccountOut:
    return EmailAccountOut(
        provider=row.provider,
        email_address=row.email_address,
        display_name=row.display_name,
        username=row.username,
        has_password=bool(row.password_encrypted),
        incoming_protocol=row.incoming_protocol,
        imap_host=row.imap_host, imap_port=row.imap_port, imap_use_ssl=row.imap_use_ssl,
        pop3_host=row.pop3_host, pop3_port=row.pop3_port, pop3_use_ssl=row.pop3_use_ssl,
        smtp_host=row.smtp_host, smtp_port=row.smtp_port, smtp_use_tls=row.smtp_use_tls,
        is_active=row.is_active,
        last_tested_at=row.last_tested_at,
        last_test_ok=row.last_test_ok,
        last_test_error=row.last_test_error,
    )


def get(db: Session, organisation_id: int) -> EmailAccountOut:
    return _to_out(_get_or_create(db, organisation_id))


def update(db: Session, organisation_id: int, payload: EmailAccountUpdateRequest) -> EmailAccountOut:
    """Does not commit -- the caller (app/api/communication.py) logs the
    audit event and commits once for the whole operation, same pattern
    as app/api/users.py's change_user_role."""
    row = _get_or_create(db, organisation_id)
    row.provider = payload.provider
    row.email_address = payload.email_address
    row.display_name = payload.display_name
    row.username = payload.username or payload.email_address
    row.incoming_protocol = payload.incoming_protocol
    row.imap_host = payload.imap_host
    row.imap_port = payload.imap_port
    row.imap_use_ssl = payload.imap_use_ssl
    row.pop3_host = payload.pop3_host
    row.pop3_port = payload.pop3_port
    row.pop3_use_ssl = payload.pop3_use_ssl
    row.smtp_host = payload.smtp_host
    row.smtp_port = payload.smtp_port
    row.smtp_use_tls = payload.smtp_use_tls
    row.is_active = payload.is_active

    if payload.password is not None:
        row.password_encrypted = encrypt_secret(payload.password) if payload.password else None

    # The saved config changed -- the last test result no longer speaks
    # to it, so don't leave a stale "OK" showing.
    row.last_tested_at = None
    row.last_test_ok = None
    row.last_test_error = None

    db.add(row)
    db.flush()
    return _to_out(row)


def _get_password(row: EmailAccount) -> str:
    if not row.password_encrypted:
        raise ValidationError("Set a mailbox password before testing the connection.")
    return decrypt_secret(row.password_encrypted)


def get_smtp_credentials(db: Session, organisation_id: int) -> dict | None:
    """SMTP half of the saved mailbox, for email_service.py to send mail
    through. None if the mailbox isn't usable for sending yet (no host,
    or no password saved)."""
    row = _get_or_create(db, organisation_id)
    if not row.smtp_host or not row.password_encrypted:
        return None
    return {
        "host": row.smtp_host,
        "port": row.smtp_port,
        "use_tls": row.smtp_use_tls,
        "username": row.username or row.email_address,
        "password": decrypt_secret(row.password_encrypted),
        "from_email": row.email_address,
        "from_name": row.display_name,
    }


def test_connection(db: Session, organisation_id: int) -> dict:
    """Opens (and immediately closes) a real connection with the saved
    settings: the chosen incoming protocol (IMAP or POP3) plus SMTP.
    Never raises -- a failure comes back as {"ok": False, "message": ...}
    so the API layer doesn't need to special-case each library's own
    exception types, and the UI can show the result inline either way."""
    row = _get_or_create(db, organisation_id)
    if not row.email_address:
        return _record_test(db, row, False, "Enter an email address first.")
    try:
        password = _get_password(row)
    except ValidationError as exc:
        return _record_test(db, row, False, exc.message)

    username = row.username or row.email_address

    try:
        if row.incoming_protocol == "imap":
            if not row.imap_host:
                return _record_test(db, row, False, "Enter an IMAP host first.")
            conn = (
                imaplib.IMAP4_SSL(row.imap_host, row.imap_port, timeout=15)
                if row.imap_use_ssl
                else imaplib.IMAP4(row.imap_host, row.imap_port, timeout=15)
            )
            try:
                conn.login(username, password)
                conn.select("INBOX", readonly=True)
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass
        else:
            if not row.pop3_host:
                return _record_test(db, row, False, "Enter a POP3 host first.")
            conn = (
                poplib.POP3_SSL(row.pop3_host, row.pop3_port, timeout=15)
                if row.pop3_use_ssl
                else poplib.POP3(row.pop3_host, row.pop3_port, timeout=15)
            )
            try:
                conn.user(username)
                conn.pass_(password)
                conn.stat()
            finally:
                try:
                    conn.quit()
                except Exception:
                    pass
    except (imaplib.IMAP4.error, poplib.error_proto, OSError, TimeoutError) as exc:
        protocol = row.incoming_protocol.upper()
        return _record_test(db, row, False, f"{protocol} connection failed: {exc}")

    if row.smtp_host:
        try:
            with smtplib.SMTP(row.smtp_host, row.smtp_port, timeout=15) as server:
                if row.smtp_use_tls:
                    server.starttls()
                server.login(username, password)
        except smtplib.SMTPNotSupportedError as exc:
            # Almost always means AUTH was attempted over a connection
            # the server never upgraded to TLS -- the standard symptom
            # of Encryption being set to "None" for this host/port.
            return _record_test(
                db, row, False,
                f"Incoming mail OK, but SMTP failed: {exc} Check that SMTP encryption "
                "is set to STARTTLS (or SSL/TLS, matching the port), not None.",
            )
        except (smtplib.SMTPException, OSError, TimeoutError) as exc:
            return _record_test(db, row, False, f"Incoming mail OK, but SMTP failed: {exc}")

    return _record_test(db, row, True, "Connected successfully (incoming and outgoing).")


def _record_test(db: Session, row: EmailAccount, ok: bool, message: str) -> dict:
    row.last_tested_at = datetime.utcnow()
    row.last_test_ok = ok
    row.last_test_error = None if ok else message
    db.add(row)
    db.commit()
    return {"ok": ok, "message": message}
