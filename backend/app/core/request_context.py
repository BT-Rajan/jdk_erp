import uuid
from contextvars import ContextVar

"""A per-request correlation id (docs/modules/api_error_handling.md #4/#5):
included in every error response so a user can quote it to support, and
in every server-side diagnostic log line so the two can be matched up.
A ContextVar rather than threading a parameter through every function
call, since logging happens from code that has no `request` object in
scope (service/model layers)."""

_request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def set_request_id(request_id: str) -> None:
    _request_id_var.set(request_id)


def get_request_id() -> str:
    return _request_id_var.get()
