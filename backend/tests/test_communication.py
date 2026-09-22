"""Tests for the Communication module's email channel
(app/api/communication.py, app/services/email_account_service.py,
app/services/email_service.py): admin gating, per-organisation scoping,
password encryption at rest, save-time validation, and both the
connection test and an actual send going through a real (mocked)
SMTP/IMAP session rather than a live server."""
import imaplib
import smtplib

from app.core.crypto import decrypt_secret
from app.models.audit_event import EMAIL_ACCOUNT_UPDATED, AuditEvent
from app.models.email_account import EmailAccount


def _headers(client, username, password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _payload(**overrides):
    payload = {
        "provider": "gmail",
        "email_address": "notify@example.com",
        "display_name": "JDK Notifications",
        "username": "notify@example.com",
        "password": "app-password-123",
        "incoming_protocol": "imap",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "imap_use_ssl": True,
        "pop3_host": "pop.gmail.com",
        "pop3_port": 995,
        "pop3_use_ssl": True,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_use_tls": True,
        "is_active": True,
    }
    payload.update(overrides)
    return payload


# --- gating / scoping --------------------------------------------------


def test_email_account_requires_authentication(client):
    response = client.get("/api/communication/email")
    assert response.status_code == 401


def test_non_admin_cannot_view_email_account(client, active_user):
    headers = _headers(client, "ada")
    response = client.get("/api/communication/email", headers=headers)
    assert response.status_code == 403


def test_non_admin_cannot_update_email_account(client, active_user):
    headers = _headers(client, "ada")
    response = client.put("/api/communication/email", json=_payload(), headers=headers)
    assert response.status_code == 403


def test_admin_sees_default_unconfigured_account(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.get("/api/communication/email", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "gmail"
    assert body["email_address"] == ""
    assert body["has_password"] is False


def test_email_accounts_are_isolated_per_organisation(client, admin_user, other_organisation, db_session):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(), headers=headers)

    rows = db_session.query(EmailAccount).all()
    assert len(rows) == 1
    assert rows[0].organisation_id == admin_user.organisation_id


# --- save / update -------------------------------------------------------


def test_admin_can_save_email_account(client, admin_user, db_session):
    headers = _headers(client, "admin_person")
    response = client.put("/api/communication/email", json=_payload(), headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["has_password"] is True
    assert "password" not in body
    assert "password_encrypted" not in body

    row = db_session.query(EmailAccount).filter_by(organisation_id=admin_user.organisation_id).first()
    assert row.password_encrypted is not None
    assert decrypt_secret(row.password_encrypted) == "app-password-123"


def test_updating_email_account_logs_audit_event(client, admin_user, db_session):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(), headers=headers)

    event = db_session.query(AuditEvent).filter_by(action=EMAIL_ACCOUNT_UPDATED).first()
    assert event is not None
    assert event.actor_user_id == admin_user.id
    assert event.organisation_id == admin_user.organisation_id


def test_omitting_password_keeps_the_existing_one(client, admin_user):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(), headers=headers)

    payload = _payload(display_name="Updated Name")
    del payload["password"]
    response = client.put("/api/communication/email", json=payload, headers=headers)

    assert response.status_code == 200
    assert response.json()["has_password"] is True
    assert response.json()["display_name"] == "Updated Name"


def test_empty_password_clears_it(client, admin_user):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(), headers=headers)

    response = client.put("/api/communication/email", json=_payload(password=""), headers=headers)

    assert response.status_code == 200
    assert response.json()["has_password"] is False


def test_saving_clears_a_stale_test_result(client, admin_user, db_session):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(), headers=headers)
    row = db_session.query(EmailAccount).filter_by(organisation_id=admin_user.organisation_id).first()
    row.last_test_ok = True
    db_session.commit()

    client.put("/api/communication/email", json=_payload(display_name="Changed"), headers=headers)

    db_session.refresh(row)
    assert row.last_test_ok is None


def test_rejects_invalid_protocol(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.put("/api/communication/email", json=_payload(incoming_protocol="ftp"), headers=headers)
    assert response.status_code == 422


def test_rejects_ssl_port_mismatch(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.put(
        "/api/communication/email", json=_payload(imap_port=993, imap_use_ssl=False), headers=headers
    )
    assert response.status_code == 422


def test_rejects_invalid_email_format(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.put("/api/communication/email", json=_payload(email_address="not-an-email"), headers=headers)
    assert response.status_code == 422


# --- providers -----------------------------------------------------------


def test_providers_lists_known_presets(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.get("/api/communication/email/providers", headers=headers)

    assert response.status_code == 200
    assert "gmail" in response.json()


# --- test connection -------------------------------------------------------


def test_test_connection_fails_without_a_password(client, admin_user):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(password=""), headers=headers)

    response = client.post("/api/communication/email/test", headers=headers)

    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_test_connection_succeeds(client, admin_user, monkeypatch):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(), headers=headers)

    class FakeImap:
        def __init__(self, *args, **kwargs):
            pass

        def login(self, *args, **kwargs):
            pass

        def select(self, *args, **kwargs):
            pass

        def logout(self):
            pass

    class FakeSmtp:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, *args, **kwargs):
            pass

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FakeImap)
    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)

    response = client.post("/api/communication/email/test", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"ok": True, "message": "Connected successfully (incoming and outgoing)."}


def test_test_connection_reports_a_real_failure(client, admin_user, monkeypatch):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(), headers=headers)

    class FailingImap:
        def __init__(self, *args, **kwargs):
            raise OSError("Name or service not known")

    monkeypatch.setattr(imaplib, "IMAP4_SSL", FailingImap)

    response = client.post("/api/communication/email/test", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "IMAP connection failed" in body["message"]


# --- send-test email -------------------------------------------------------


def test_send_test_email_requires_a_configured_mailbox(client, admin_user):
    headers = _headers(client, "admin_person")
    response = client.post(
        "/api/communication/email/send-test", json={"to_email": "someone@example.com"}, headers=headers
    )
    assert response.status_code == 400


def test_send_test_email_sends_through_the_saved_mailbox(client, admin_user, monkeypatch):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(), headers=headers)

    sent = {}

    class FakeSmtp:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, *args, **kwargs):
            pass

        def sendmail(self, from_addr, to_addrs, msg):
            sent["from"] = from_addr
            sent["to"] = to_addrs

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)

    response = client.post(
        "/api/communication/email/send-test", json={"to_email": "someone@example.com"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert sent["to"] == ["someone@example.com"]


def test_send_test_email_rejects_invalid_recipient(client, admin_user):
    headers = _headers(client, "admin_person")
    client.put("/api/communication/email", json=_payload(), headers=headers)

    response = client.post(
        "/api/communication/email/send-test", json={"to_email": "not-an-email"}, headers=headers
    )
    assert response.status_code == 422
