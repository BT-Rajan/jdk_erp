"""Tests for docs/modules/api_error_handling.md: the AppError hierarchy,
the standard error envelope, full field-level validation errors (not
just the first, unlike jdk_clean's equivalent), DB/unexpected-error
containment, and the request-id correlation header."""
from sqlalchemy.exc import IntegrityError

from app.core.errors import (
    AccessDeniedError,
    AppError,
    AuthError,
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    RateLimitedError,
    ValidationError,
)


def _headers(client, username, password="Str0ng!Pass"):
    login = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- the exception hierarchy itself ---------------------------------------


def test_each_app_error_subclass_has_a_distinct_code_and_status():
    cases = [
        (ValidationError, "VALIDATION_ERROR", 422),
        (AuthError, "AUTHENTICATION_ERROR", 401),
        (AccessDeniedError, "ACCESS_DENIED", 403),
        (NotFoundError, "NOT_FOUND", 404),
        (ConflictError, "CONFLICT", 409),
        (BusinessRuleError, "BUSINESS_RULE_ERROR", 400),
        (RateLimitedError, "RATE_LIMITED", 429),
    ]
    for cls, code, status_code in cases:
        exc = cls()
        assert exc.code == code
        assert exc.status_code == status_code
        assert exc.message  # every class has a safe default message


def test_app_error_carries_a_custom_message_and_fields():
    exc = ValidationError("Quantity must be greater than zero.", fields={"quantity": "must be > 0"})
    assert exc.message == "Quantity must be greater than zero."
    assert exc.fields == {"quantity": "must be > 0"}
    assert str(exc) == "Quantity must be greater than zero."


# --- the envelope, end to end ----------------------------------------------


def test_error_envelope_shape(client, active_user):
    response = client.get("/api/users/999999", headers=_headers(client, "ada"))
    assert response.status_code == 404
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"]
    assert "request_id" in body and body["request_id"]


def test_authentication_error_uses_standard_envelope(client):
    response = client.get("/api/audit-events")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_ERROR"


def test_access_denied_uses_standard_envelope(client, active_user):
    response = client.get("/api/audit-events", headers=_headers(client, "ada"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCESS_DENIED"


# --- full field-level validation (jdk_clean only surfaced the first) ------


def test_validation_error_reports_every_invalid_field_not_just_the_first(client):
    """docs/modules/api_error_handling.md #7 -- return field-level errors
    so the UI can show them beside the relevant field. jdk_clean's
    equivalent only ever surfaced exc.errors()[0] -- see
    docs/audit/API_ERROR_HANDLING_AUDIT.md."""
    response = client.post("/api/auth/login", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert set(body["error"]["fields"].keys()) == {"username", "password"}


def test_custom_field_validator_message_surfaces_verbatim(client, admin_user, active_user):
    """A @field_validator's own ValueError message is safe, hand-written
    text -- surfaced as-is, not replaced by a generic fallback."""
    headers = _headers(client, "admin_person")
    response = client.patch(f"/api/users/{active_user.id}/role", json={"role": "superhero"}, headers=headers)
    assert response.status_code == 422
    fields = response.json()["error"]["fields"]
    assert "role" in fields
    assert "superhero" not in fields["role"]  # never echoes the raw invalid input in a way that could be exploited
    assert "must be one of" in fields["role"]


# --- DB and unexpected errors never leak raw detail ------------------------


def test_integrity_error_becomes_safe_conflict_response():
    import asyncio

    from starlette.requests import Request

    from app.core.error_handlers import register_exception_handlers
    from fastapi import FastAPI

    app = FastAPI()
    register_exception_handlers(app)
    handler = app.exception_handlers[IntegrityError]

    scope = {"type": "http", "method": "GET", "path": "/test", "headers": []}
    request = Request(scope)

    exc = IntegrityError("INSERT INTO users ...", {}, Exception("UNIQUE constraint failed: users.email"))
    response = asyncio.get_event_loop().run_until_complete(handler(request, exc))

    assert response.status_code == 409
    body = response.body.decode()
    assert "UNIQUE constraint" not in body
    assert "users.email" not in body
    assert "CONFLICT" in body


def test_unhandled_exception_returns_generic_message_not_the_real_error(client, active_user, monkeypatch):
    """Uses its own client with raise_server_exceptions=False: the default
    `client` fixture re-raises unhandled exceptions (so a real bug fails
    the test loudly), but here we're deliberately checking what a real
    caller over HTTP would see -- the global handler's safe response."""
    from fastapi.testclient import TestClient

    from app.api import users as users_api
    from app.main import app

    def _boom(*args, **kwargs):
        raise RuntimeError("division by zero at /home/user/jdk_erp/backend/app/services/some_module.py:42")

    monkeypatch.setattr(users_api.user_service, "team_ids_for_users", _boom)

    headers = _headers(client, "ada")
    lenient_client = TestClient(app, raise_server_exceptions=False)
    response = lenient_client.get("/api/users", headers=headers)

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "SERVER_ERROR"
    assert body["error"]["message"] == "Something went wrong. Please try again."
    raw = response.text
    assert "RuntimeError" not in raw
    assert "some_module.py" not in raw
    assert "/home/user" not in raw


# --- request-id correlation -------------------------------------------


def test_request_id_header_present_on_success(client):
    response = client.get("/health")
    assert response.headers["x-request-id"]


def test_request_id_header_matches_error_body(client):
    response = client.get("/api/users/999999")
    header_id = response.headers["x-request-id"]
    body_id = response.json()["request_id"]
    assert header_id == body_id


def test_app_error_is_a_valid_exception_type():
    assert issubclass(AuthError, AppError)
    assert issubclass(NotFoundError, AppError)
