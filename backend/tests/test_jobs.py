"""Tests for docs/modules/background_jobs.md."""
from datetime import datetime, timedelta

import pytest

from app.core import job_registry
from app.core.job_registry import RetryableJobError, register_job_handler
from app.models.job import COMPLETED, FAILED, PENDING, RUNNING, Job
from app.services import job_service
from app.services.job_worker import run_worker


def _login_headers(client, username="ada", password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def calls():
    """A list the test's own handler appends to, so a test can assert
    how many times (and with what payload) it actually ran."""
    return []


@pytest.fixture()
def succeeding_job_type(calls):
    def handler(db, payload):
        calls.append(payload)

    register_job_handler("test_succeeds", handler)
    yield "test_succeeds"
    job_registry._registry.pop("test_succeeds", None)


@pytest.fixture()
def retryable_job_type(calls):
    def handler(db, payload):
        calls.append(payload)
        raise RetryableJobError("temporary glitch")

    register_job_handler("test_retryable", handler)
    yield "test_retryable"
    job_registry._registry.pop("test_retryable", None)


@pytest.fixture()
def non_retryable_job_type(calls):
    def handler(db, payload):
        calls.append(payload)
        raise ValueError("bad business data")

    register_job_handler("test_non_retryable", handler)
    yield "test_non_retryable"
    job_registry._registry.pop("test_non_retryable", None)


class TestDispatch:
    def test_dispatch_refuses_an_unregistered_job_type(self, db_session):
        with pytest.raises(ValueError, match="registered"):
            job_service.dispatch(db_session, job_type="nope_not_registered")

    def test_dispatch_creates_a_pending_job(self, db_session, succeeding_job_type):
        job = job_service.dispatch(db_session, job_type=succeeding_job_type, payload={"x": 1})
        db_session.commit()
        assert job.status == PENDING
        assert job.attempts == 0

    def test_idempotency_key_returns_the_same_job_on_a_repeat_dispatch(self, db_session, succeeding_job_type):
        job1 = job_service.dispatch(db_session, job_type=succeeding_job_type, idempotency_key="daily:2026-09-22")
        db_session.commit()
        job2 = job_service.dispatch(db_session, job_type=succeeding_job_type, idempotency_key="daily:2026-09-22")
        db_session.commit()
        assert job1.id == job2.id
        assert db_session.query(Job).filter(Job.idempotency_key == "daily:2026-09-22").count() == 1

    def test_different_idempotency_keys_create_different_jobs(self, db_session, succeeding_job_type):
        job1 = job_service.dispatch(db_session, job_type=succeeding_job_type, idempotency_key="daily:2026-09-22")
        job2 = job_service.dispatch(db_session, job_type=succeeding_job_type, idempotency_key="daily:2026-09-23")
        db_session.commit()
        assert job1.id != job2.id


class TestClaiming:
    def test_claim_pending_jobs_marks_them_running(self, db_session, succeeding_job_type):
        job_service.dispatch(db_session, job_type=succeeding_job_type)
        db_session.commit()
        claimed = job_service.claim_pending_jobs(db_session, limit=10)
        assert len(claimed) == 1
        assert claimed[0].status == RUNNING
        assert claimed[0].started_at is not None

    def test_a_claimed_job_is_not_claimed_again(self, db_session, succeeding_job_type):
        job_service.dispatch(db_session, job_type=succeeding_job_type)
        db_session.commit()
        first = job_service.claim_pending_jobs(db_session, limit=10)
        second = job_service.claim_pending_jobs(db_session, limit=10)
        assert len(first) == 1
        assert len(second) == 0

    def test_a_job_scheduled_in_the_future_is_not_claimed_yet(self, db_session, succeeding_job_type):
        job_service.dispatch(db_session, job_type=succeeding_job_type, scheduled_at=datetime.utcnow() + timedelta(hours=1))
        db_session.commit()
        assert job_service.claim_pending_jobs(db_session, limit=10) == []

    def test_claim_respects_the_limit(self, db_session, succeeding_job_type):
        for _ in range(3):
            job_service.dispatch(db_session, job_type=succeeding_job_type)
        db_session.commit()
        assert len(job_service.claim_pending_jobs(db_session, limit=2)) == 2


class TestProcessing:
    def test_a_successful_job_completes(self, db_session, succeeding_job_type, calls):
        job_service.dispatch(db_session, job_type=succeeding_job_type, payload={"key": "value"})
        db_session.commit()
        [job] = job_service.claim_pending_jobs(db_session, limit=10)
        job_service.process_one(db_session, job)
        assert job.status == COMPLETED
        assert job.finished_at is not None
        assert calls == [{"key": "value"}]

    def test_a_retryable_failure_goes_back_to_pending_with_a_later_schedule(self, db_session, retryable_job_type):
        job_service.dispatch(db_session, job_type=retryable_job_type, max_attempts=3)
        db_session.commit()
        [job] = job_service.claim_pending_jobs(db_session, limit=10)
        before = job.scheduled_at
        job_service.process_one(db_session, job)
        assert job.status == PENDING
        assert job.attempts == 1
        assert job.scheduled_at > before
        assert job.error_type == "RetryableJobError"

    def test_exhausting_retries_reaches_failed(self, db_session, retryable_job_type):
        job_service.dispatch(db_session, job_type=retryable_job_type, max_attempts=2, scheduled_at=datetime.utcnow())
        db_session.commit()
        job = db_session.query(Job).filter(Job.job_type == retryable_job_type).one()

        for _ in range(2):
            job.status = PENDING
            job.scheduled_at = datetime.utcnow()
            db_session.add(job)
            db_session.commit()
            [claimed] = job_service.claim_pending_jobs(db_session, limit=10)
            job_service.process_one(db_session, claimed)

        assert job.status == FAILED
        assert job.attempts == 2
        assert job.finished_at is not None

    def test_a_non_retryable_failure_goes_straight_to_failed(self, db_session, non_retryable_job_type):
        job_service.dispatch(db_session, job_type=non_retryable_job_type)
        db_session.commit()
        [job] = job_service.claim_pending_jobs(db_session, limit=10)
        job_service.process_one(db_session, job)
        assert job.status == FAILED
        assert job.attempts == 1
        assert job.error_type == "ValueError"

    def test_error_message_is_truncated_not_a_full_dump(self, db_session):
        def handler(db, payload):
            raise ValueError("x" * 10_000)

        register_job_handler("test_huge_error", handler)
        try:
            job_service.dispatch(db_session, job_type="test_huge_error")
            db_session.commit()
            [job] = job_service.claim_pending_jobs(db_session, limit=10)
            job_service.process_one(db_session, job)
            assert len(job.error_message) <= 500
        finally:
            job_registry._registry.pop("test_huge_error", None)

    def test_an_unregistered_job_type_at_process_time_fails_without_retry(self, db_session, succeeding_job_type):
        job_service.dispatch(db_session, job_type=succeeding_job_type)
        db_session.commit()
        [job] = job_service.claim_pending_jobs(db_session, limit=10)
        job_registry._registry.pop(succeeding_job_type, None)  # simulate a handler removed after dispatch
        job_service.process_one(db_session, job)
        assert job.status == FAILED
        assert job.error_type == "unregistered_job_type"

    def test_a_failed_handlers_partial_writes_are_rolled_back(self, db_session, organisation):
        """The db.rollback() fix in process_one(): a handler that writes
        something and then fails must not have that write survive
        alongside the job's FAILED status
        (docs/modules/database_transaction_integrity.md #6)."""
        from app.models.team import Team

        def handler(db, payload):
            db.add(Team(organisation_id=organisation.id, name="Should Not Persist", is_active=True))
            db.flush()
            raise ValueError("boom after the write")

        register_job_handler("test_partial_write", handler)
        try:
            job_service.dispatch(db_session, job_type="test_partial_write")
            db_session.commit()
            [job] = job_service.claim_pending_jobs(db_session, limit=10)
            job_service.process_one(db_session, job)
            assert job.status == FAILED
            assert db_session.query(Team).filter(Team.name == "Should Not Persist").count() == 0
        finally:
            job_registry._registry.pop("test_partial_write", None)


class TestRecovery:
    def test_abandoned_running_jobs_are_recovered(self, db_session, succeeding_job_type):
        job_service.dispatch(db_session, job_type=succeeding_job_type)
        db_session.commit()
        [job] = job_service.claim_pending_jobs(db_session, limit=10)
        job.started_at = datetime.utcnow() - timedelta(hours=1)
        db_session.add(job)
        db_session.commit()

        recovered = job_service.recover_abandoned_jobs(db_session)

        assert recovered == 1
        assert job.status == PENDING
        assert job.attempts == 1

    def test_a_recently_started_running_job_is_not_recovered(self, db_session, succeeding_job_type):
        job_service.dispatch(db_session, job_type=succeeding_job_type)
        db_session.commit()
        job_service.claim_pending_jobs(db_session, limit=10)

        assert job_service.recover_abandoned_jobs(db_session) == 0


class TestIdempotentHandler:
    def test_cleanup_expired_refresh_tokens_is_safe_to_run_twice(self, db_session, active_user):
        from app.models.refresh_token import RefreshToken

        db_session.add(RefreshToken(jti="expired-a", user_id=active_user.id, expires_at=datetime.utcnow() - timedelta(days=1)))
        db_session.add(RefreshToken(jti="valid-a", user_id=active_user.id, expires_at=datetime.utcnow() + timedelta(days=1)))
        db_session.commit()

        job_service.dispatch(db_session, job_type="cleanup_expired_refresh_tokens")
        db_session.commit()
        [job] = job_service.claim_pending_jobs(db_session, limit=10)
        job_service.process_one(db_session, job)
        assert job.status == COMPLETED

        # Running it again (a second dispatch, e.g. a duplicate cron
        # fire without the idempotency key) must not error or affect
        # the still-valid token.
        job_service.dispatch(db_session, job_type="cleanup_expired_refresh_tokens")
        db_session.commit()
        [job2] = job_service.claim_pending_jobs(db_session, limit=10)
        job_service.process_one(db_session, job2)
        assert job2.status == COMPLETED

        remaining = db_session.query(RefreshToken).all()
        assert [t.jti for t in remaining] == ["valid-a"]


class TestWorker:
    def test_run_worker_claims_and_processes_pending_jobs(self, db_session, succeeding_job_type, calls):
        job_service.dispatch(db_session, job_type=succeeding_job_type, payload={"n": 1})
        db_session.commit()

        run_worker(max_iterations=1, poll_interval_seconds=0)

        job = db_session.query(Job).filter(Job.job_type == succeeding_job_type).one()
        assert job.status == COMPLETED
        assert calls == [{"n": 1}]


class TestStatsEndpoint:
    def test_stats_requires_admin(self, client, active_user):
        headers = _login_headers(client)
        response = client.get("/api/jobs/stats", headers=headers)
        assert response.status_code == 403

    def test_stats_reports_counts(self, client, admin_user, db_session, succeeding_job_type):
        job_service.dispatch(db_session, job_type=succeeding_job_type)
        db_session.commit()

        headers = _login_headers(client, "admin_person")
        response = client.get("/api/jobs/stats", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["pending_count"] >= 1
        assert body["oldest_pending_scheduled_at"] is not None
