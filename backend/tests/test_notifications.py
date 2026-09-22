"""Tests for docs/modules/notifications.md: the one notify() service,
its recipient-only authorization boundary (a user only ever sees their
own notifications), the email path going through a real background job
rather than sending inline, and the retention cleanup job."""
import json
import smtplib
from datetime import datetime, timedelta

import pytest

from app.jobs.cleanup_old_read_notifications import run as run_cleanup
from app.jobs.send_notification_email import JOB_TYPE as SEND_EMAIL_JOB_TYPE
from app.models.job import COMPLETED, PENDING, Job
from app.models.notification import ACTION_REQUIRED, INFO, Notification
from app.services import job_service, notification_service


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _email_payload(**overrides):
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


# --- notify() ----------------------------------------------------------


def test_notify_creates_a_notification_for_one_user(db_session, active_user):
    rows = notification_service.notify(
        db_session, active_user, type=INFO, title="Hello", message="World"
    )
    db_session.commit()
    assert len(rows) == 1
    assert rows[0].recipient_user_id == active_user.id
    assert rows[0].organisation_id == active_user.organisation_id


def test_notify_creates_notifications_for_several_users(db_session, active_user, admin_user):
    rows = notification_service.notify(
        db_session, [active_user, admin_user], type=INFO, title="Hello", message="World"
    )
    db_session.commit()
    assert {r.recipient_user_id for r in rows} == {active_user.id, admin_user.id}


def test_notify_rejects_an_unknown_type(db_session, active_user):
    with pytest.raises(ValueError, match="Unknown notification type"):
        notification_service.notify(db_session, active_user, type="BOGUS", title="Hi", message="Hi")


# --- GET /api/notifications ----------------------------------------------


def test_notifications_require_authentication(client):
    response = client.get("/api/notifications")
    assert response.status_code == 401


def test_user_only_sees_their_own_notifications(client, db_session, active_user, admin_user):
    notification_service.notify(db_session, active_user, type=INFO, title="For Ada", message="m")
    notification_service.notify(db_session, admin_user, type=INFO, title="For Admin", message="m")
    db_session.commit()

    headers = _login_headers(client, "ada")
    response = client.get("/api/notifications", headers=headers)

    assert response.status_code == 200
    titles = {n["title"] for n in response.json()}
    assert titles == {"For Ada"}


def test_unread_only_filter(client, db_session, active_user):
    notification_service.notify(db_session, active_user, type=INFO, title="Unread", message="m")
    read_row = notification_service.notify(db_session, active_user, type=INFO, title="Read", message="m")[0]
    db_session.commit()
    notification_service.mark_read(db_session, active_user, read_row.id)
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/notifications?unread_only=true", headers=headers)
    assert {n["title"] for n in response.json()} == {"Unread"}


# --- unread-count ----------------------------------------------------------


def test_unread_count_reflects_only_the_callers_own(client, db_session, active_user, admin_user):
    notification_service.notify(db_session, active_user, type=INFO, title="a", message="m")
    notification_service.notify(db_session, active_user, type=INFO, title="b", message="m")
    notification_service.notify(db_session, admin_user, type=INFO, title="c", message="m")
    db_session.commit()

    headers = _login_headers(client)
    response = client.get("/api/notifications/unread-count", headers=headers)
    assert response.json() == {"count": 2}


# --- mark read / mark all read -------------------------------------------


def test_mark_read_marks_only_that_notification(client, db_session, active_user):
    row1 = notification_service.notify(db_session, active_user, type=INFO, title="one", message="m")[0]
    row2 = notification_service.notify(db_session, active_user, type=INFO, title="two", message="m")[0]
    db_session.commit()

    headers = _login_headers(client)
    response = client.patch(f"/api/notifications/{row1.id}/read", headers=headers)
    assert response.status_code == 204

    db_session.refresh(row1)
    db_session.refresh(row2)
    assert row1.is_read is True
    assert row1.read_at is not None
    assert row2.is_read is False


def test_mark_read_on_another_users_notification_returns_404(client, db_session, active_user, admin_user):
    headers = _login_headers(client, "admin_person")
    other_row = notification_service.notify(db_session, active_user, type=INFO, title="not yours", message="m")[0]
    db_session.commit()

    response = client.patch(f"/api/notifications/{other_row.id}/read", headers=headers)
    assert response.status_code == 404

    db_session.refresh(other_row)
    assert other_row.is_read is False


def test_mark_read_on_nonexistent_notification_returns_404(client, active_user):
    headers = _login_headers(client)
    response = client.patch("/api/notifications/999999/read", headers=headers)
    assert response.status_code == 404


def test_mark_all_read_marks_only_the_callers_unread(client, db_session, active_user, admin_user):
    a1 = notification_service.notify(db_session, active_user, type=INFO, title="a1", message="m")[0]
    a2 = notification_service.notify(db_session, active_user, type=INFO, title="a2", message="m")[0]
    other = notification_service.notify(db_session, admin_user, type=INFO, title="other", message="m")[0]
    db_session.commit()

    headers = _login_headers(client)
    response = client.post("/api/notifications/mark-all-read", headers=headers)
    assert response.status_code == 204

    db_session.refresh(a1)
    db_session.refresh(a2)
    db_session.refresh(other)
    assert a1.is_read and a2.is_read
    assert other.is_read is False


# --- real call sites: role change, team assignment ------------------------


def test_role_change_notifies_the_affected_user(client, admin_user, active_user, db_session):
    headers = _login_headers(client, "admin_person")
    response = client.patch(f"/api/users/{active_user.id}/role", json={"role": "manager"}, headers=headers)
    assert response.status_code == 204

    notification = (
        db_session.query(Notification).filter_by(recipient_user_id=active_user.id).order_by(Notification.id.desc()).first()
    )
    assert notification is not None
    assert "manager" in notification.message


def test_adding_team_member_notifies_the_added_user(client, admin_user, active_user, sales_team, db_session):
    headers = _login_headers(client, "admin_person")
    response = client.post(f"/api/teams/{sales_team.id}/members", json={"user_id": active_user.id}, headers=headers)
    assert response.status_code == 204

    notification = (
        db_session.query(Notification).filter_by(recipient_user_id=active_user.id).order_by(Notification.id.desc()).first()
    )
    assert notification is not None
    assert sales_team.name in notification.message


# --- email path: dispatch + job -------------------------------------------


def test_send_email_true_dispatches_a_background_job_not_an_inline_send(db_session, active_user):
    rows = notification_service.notify(
        db_session, active_user, type=ACTION_REQUIRED, title="Approve", message="Please approve", send_email=True
    )
    db_session.commit()

    job = db_session.query(Job).filter_by(job_type=SEND_EMAIL_JOB_TYPE).first()
    assert job is not None
    assert job.status == PENDING
    assert json.loads(job.payload) == {"notification_id": rows[0].id}


def test_send_email_false_by_default_dispatches_no_job(db_session, active_user):
    notification_service.notify(db_session, active_user, type=INFO, title="Hi", message="m")
    db_session.commit()
    assert db_session.query(Job).filter_by(job_type=SEND_EMAIL_JOB_TYPE).count() == 0


def test_email_job_is_a_noop_without_a_configured_mailbox(db_session, active_user):
    row = notification_service.notify(
        db_session, active_user, type=INFO, title="Hi", message="Body text", send_email=True
    )[0]
    db_session.commit()

    job = db_session.query(Job).filter_by(job_type=SEND_EMAIL_JOB_TYPE).first()
    job_service.process_one(db_session, job)

    db_session.refresh(job)
    assert job.status == COMPLETED


def test_email_job_sends_through_the_organisations_mailbox(client, db_session, admin_user, active_user, monkeypatch):
    headers = _login_headers(client, "admin_person")
    client.put("/api/communication/email", json=_email_payload(), headers=headers)

    row = notification_service.notify(
        db_session, active_user, type=INFO, title="Hi Ada", message="Body text", send_email=True
    )[0]
    db_session.commit()

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
            sent["to"] = to_addrs
            sent["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSmtp)

    job = db_session.query(Job).filter_by(job_type=SEND_EMAIL_JOB_TYPE).first()
    job_service.process_one(db_session, job)

    db_session.refresh(job)
    assert job.status == COMPLETED
    assert sent["to"] == [active_user.email]
    assert "Hi Ada" in sent["msg"]
    assert "Body text" in sent["msg"]


def test_email_job_retries_on_a_temporary_smtp_failure(client, db_session, admin_user, active_user, monkeypatch):
    headers = _login_headers(client, "admin_person")
    client.put("/api/communication/email", json=_email_payload(), headers=headers)

    notification_service.notify(db_session, active_user, type=INFO, title="Hi", message="m", send_email=True)
    db_session.commit()

    class FailingSmtp:
        def __init__(self, *args, **kwargs):
            raise OSError("Connection refused")

    monkeypatch.setattr(smtplib, "SMTP", FailingSmtp)

    job = db_session.query(Job).filter_by(job_type=SEND_EMAIL_JOB_TYPE).first()
    job_service.process_one(db_session, job)

    db_session.refresh(job)
    assert job.status == PENDING  # retry-eligible, not FAILED
    assert job.attempts == 1


def test_email_job_is_a_noop_when_notification_no_longer_exists(db_session):
    job = job_service.dispatch(db_session, job_type=SEND_EMAIL_JOB_TYPE, payload={"notification_id": 999999})
    db_session.commit()

    job_service.process_one(db_session, job)
    db_session.refresh(job)
    assert job.status == COMPLETED


# --- retention -------------------------------------------------------------


def test_cleanup_deletes_only_old_read_notifications(db_session, active_user):
    old_read = notification_service.notify(db_session, active_user, type=INFO, title="old read", message="m")[0]
    recent_read = notification_service.notify(db_session, active_user, type=INFO, title="recent read", message="m")[0]
    unread = notification_service.notify(db_session, active_user, type=INFO, title="unread", message="m")[0]
    db_session.commit()

    old_read.is_read = True
    old_read.read_at = datetime.utcnow() - timedelta(days=200)
    recent_read.is_read = True
    recent_read.read_at = datetime.utcnow() - timedelta(days=1)
    db_session.commit()

    # Captured before the cleanup deletes a row out from under the ORM
    # identity map -- re-reading .id off a since-deleted instance raises
    # ObjectDeletedError once its attributes expire on commit.
    old_read_id, recent_read_id, unread_id = old_read.id, recent_read.id, unread.id

    run_cleanup(db_session, {})
    db_session.commit()

    remaining_ids = {n.id for n in db_session.query(Notification).all()}
    assert old_read_id not in remaining_ids
    assert recent_read_id in remaining_ids
    assert unread_id in remaining_ids
