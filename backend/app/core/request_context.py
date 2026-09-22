import uuid
from contextvars import ContextVar

"""A per-request correlation id (docs/modules/api_error_handling.md #4/#5):
included in every error response so a user can quote it to support, and
in every server-side diagnostic log line so the two can be matched up.
A ContextVar rather than threading a parameter through every function
call, since logging happens from code that has no `request` object in
scope (service/model layers)."""

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Same shape as request_id -- set once identity resolves
# (app.api.deps.get_current_user), read from anywhere (services, the
# structured logging in app/core/logging.py) with no request object in
# scope (docs/modules/logging_request_tracing.md #2/#3).
_user_id_var: ContextVar[int | None] = ContextVar("user_id", default=None)
_organisation_id_var: ContextVar[int | None] = ContextVar("organisation_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


def get_request_id() -> str:
    return _request_id_var.get()


def reset_request_context() -> None:
    """Clears user/organisation identity at the start of every request
    (app.core.request_id_middleware), so an unauthenticated request can
    never inherit a value left over from a previous request reusing the
    same async context."""
    _user_id_var.set(None)
    _organisation_id_var.set(None)


def set_user_context(user_id: int, organisation_id: int) -> None:
    _user_id_var.set(user_id)
    _organisation_id_var.set(organisation_id)


def get_user_id() -> int | None:
    return _user_id_var.get()


def get_organisation_id() -> int | None:
    return _organisation_id_var.get()
