"""Tests for docs/modules/logging_request_tracing.md."""
import json
import logging

import pytest
from starlette.testclient import TestClient

from app.api import auth as auth_api
from app.core.config import settings
from app.core.logging import _StructuredFormatter, get_logger, log, redact
from app.core.request_context import reset_request_context, set_request_id, set_user_context
from app.main import app

PASSWORD = "Str0ng!Pass"


class _CapturingHandler(logging.Handler):
    """Formats each record *at emit time*, like the real StreamHandler
    app.core.logging.configure_logging() installs -- not deferred until
    later. This matters here specifically: TestClient runs the ASGI app
    through its own thread/event-loop portal, so a request's ContextVars
    (request_id, user_id, organisation_id) are only actually current
    *during* that request's own execution. Formatting later, back in the
    test function's own thread, would read the ContextVar defaults
    instead -- a test artifact, not a bug in the app's real logging path
    (which already formats synchronously inside emit(), within the
    request's own context, exactly like this)."""

    def __init__(self):
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.entries: list[dict] = []
        self._formatter = _StructuredFormatter()

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)
        self.entries.append(json.loads(self._formatter.format(record)))


@pytest.fixture()
def captured_logs():
    """Attaches a capturing handler directly to the "jdk" logger --
    independent of pytest's own caplog/root-logger capture, which
    app.core.logging.configure_logging() deliberately bypasses
    (`propagate = False`, docs/modules/logging_request_tracing.md #1)."""
    handler = _CapturingHandler()
    jdk_logger = logging.getLogger("jdk")
    jdk_logger.addHandler(handler)
    jdk_logger.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        jdk_logger.removeHandler(handler)


def _formatted(handler: _CapturingHandler) -> list[dict]:
    return handler.entries


class TestRedaction:
    def test_redact_masks_known_sensitive_keys(self):
        result = redact({"password": "hunter2", "user_id": 1, "token": "abc.def.ghi"})
        assert result == {"password": "***", "user_id": 1, "token": "***"}

    def test_redact_is_case_insensitive(self):
        assert redact({"PASSWORD": "hunter2"}) == {"PASSWORD": "***"}

    def test_log_helper_never_lets_a_sensitive_field_through(self, captured_logs):
        logger = get_logger("test")
        log(logger, logging.INFO, "issued token", access_token="super-secret-value", user_id=1)
        [entry] = _formatted(captured_logs)
        assert entry["access_token"] == "***"
        assert "super-secret-value" not in json.dumps(entry)


class TestStructuredFields:
    def test_formatter_includes_the_minimum_fields(self, captured_logs):
        set_request_id("req-abc123")
        set_user_context(7, 3)
        logger = get_logger("test")
        log(logger, logging.INFO, "did a thing", action="thing.done", duration_ms=12.5)
        [entry] = _formatted(captured_logs)

        for field in ("timestamp", "level", "request_id", "user_id", "organisation_id", "module", "message"):
            assert field in entry
        assert entry["level"] == "INFO"
        assert entry["request_id"] == "req-abc123"
        assert entry["user_id"] == 7
        assert entry["organisation_id"] == 3
        assert entry["message"] == "did a thing"
        assert entry["action"] == "thing.done"
        assert entry["duration_ms"] == 12.5
        reset_request_context()

    def test_exc_info_attaches_a_stack_trace(self, captured_logs):
        logger = get_logger("test")
        try:
            raise ValueError("boom")
        except ValueError:
            log(logger, logging.ERROR, "unexpected failure", exc_info=True)
        [entry] = _formatted(captured_logs)
        assert "stack_trace" in entry
        assert "ValueError: boom" in entry["stack_trace"]


class TestRequestTracing:
    def test_request_id_is_consistent_across_every_log_line_for_one_request(self, client, captured_logs):
        response = client.get("/api/nope")
        assert response.status_code == 404

        entries = _formatted(captured_logs)
        request_ids = {entry["request_id"] for entry in entries if entry["module"] in ("jdk.errors", "jdk.request")}
        assert len(request_ids) == 1, entries

        body_request_id = response.json()["request_id"]
        assert body_request_id in request_ids
        assert response.headers["X-Request-ID"] == body_request_id

    def test_request_completion_line_carries_the_error_code(self, client, captured_logs):
        client.get("/api/nope")
        [request_line] = [e for e in _formatted(captured_logs) if e["module"] == "jdk.request"]
        assert request_line["error_code"] == "NOT_FOUND"
        assert request_line["status_code"] == 404

    def test_authenticated_request_logs_carry_user_and_organisation_id(self, client, captured_logs, active_user):
        login = client.post("/api/auth/login", json={"username": active_user.username, "password": PASSWORD})
        token = login.json()["access_token"]
        captured_logs.records.clear()
        captured_logs.entries.clear()

        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

        [request_line] = [e for e in _formatted(captured_logs) if e["module"] == "jdk.request"]
        assert request_line["user_id"] == active_user.id
        assert request_line["organisation_id"] == active_user.organisation_id

    def test_slow_requests_log_at_warn(self, client, captured_logs, monkeypatch):
        monkeypatch.setattr(settings, "SLOW_REQUEST_THRESHOLD_MS", -1)
        client.get("/health")
        [request_line] = [r for r in captured_logs.records if r.name == "jdk.request"]
        assert request_line.levelno == logging.WARNING

    def test_server_errors_log_at_error(self, client, captured_logs, active_user, monkeypatch):
        # Uses its own client with raise_server_exceptions=False, same as
        # tests/test_api_error_handling.py's equivalent test -- the
        # default TestClient re-raises an unhandled exception for
        # visibility rather than letting the app's own 500 handler
        # produce a normal response.
        def _boom(*args, **kwargs):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(auth_api.user_service, "team_ids_for_users", _boom)

        login = client.post("/api/auth/login", json={"username": active_user.username, "password": PASSWORD})
        token = login.json()["access_token"]
        captured_logs.records.clear()
        captured_logs.entries.clear()

        lenient_client = TestClient(app, raise_server_exceptions=False)
        response = lenient_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 500
        levels = {r.levelno for r in captured_logs.records if r.name == "jdk.request"}
        assert logging.ERROR in levels


class TestNoSensitiveDataLogged:
    def test_password_never_appears_in_logs_for_a_login_attempt(self, client, captured_logs, active_user):
        client.post("/api/auth/login", json={"username": active_user.username, "password": PASSWORD})
        entries = _formatted(captured_logs)
        assert PASSWORD not in json.dumps(entries)

    def test_password_never_appears_in_logs_for_a_failed_login_attempt(self, client, captured_logs, active_user):
        client.post("/api/auth/login", json={"username": active_user.username, "password": "wrong-one"})
        entries = _formatted(captured_logs)
        assert "wrong-one" not in json.dumps(entries)
