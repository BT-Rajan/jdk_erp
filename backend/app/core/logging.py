import json
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.request_context import get_organisation_id, get_request_id, get_user_id

# Never write one of these values to a log line, even if a caller passes
# it as a structured field by mistake (docs/modules/logging_request_tracing.md
# #7). Matched case-insensitively against each extra field's key.
_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "reset_token",
        "session_token",
        "api_key",
        "secret",
        "jwt_secret_key",
        "authorization",
        "credit_card",
        "card_number",
        "cvv",
    }
)
_REDACTED = "***"


def redact(fields: dict) -> dict:
    """Masks any field whose key looks sensitive, rather than trusting
    every call site to remember never to pass one -- defense in depth on
    top of "just don't log it" (docs/modules/logging_request_tracing.md #7)."""
    return {key: (_REDACTED if key.lower() in _SENSITIVE_KEYS else value) for key, value in fields.items()}


class _StructuredFormatter(logging.Formatter):
    """The one log line shape for the whole application
    (docs/modules/logging_request_tracing.md #1/#3) -- request_id/user_id/
    organisation_id are injected here, from context, so no call site has
    to remember to pass them. One JSON object per line: simple enough to
    read by eye in development and to ship to any log aggregator in
    production, without adopting a logging platform."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "request_id": get_request_id(),
            "user_id": get_user_id(),
            "organisation_id": get_organisation_id(),
            "module": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(redact(extra))
        if record.exc_info:
            payload["stack_trace"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def configure_logging() -> None:
    """Called once at application startup (app/main.py) -- the one place
    the log format/level/handler is set up, so no module configures its
    own logging (docs/modules/logging_request_tracing.md #1)."""
    global _configured
    if _configured:
        return
    root = logging.getLogger("jdk")
    root.setLevel(settings.LOG_LEVEL)
    handler = logging.StreamHandler()
    handler.setFormatter(_StructuredFormatter())
    root.addHandler(handler)
    root.propagate = False
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """The one way any module gets a logger -- always a child of "jdk",
    so it inherits the central handler/formatter/level rather than
    inventing its own (docs/modules/logging_request_tracing.md #1)."""
    configure_logging()
    return logging.getLogger(f"jdk.{name}")


def log(logger: logging.Logger, level: int, message: str, *, exc_info: bool = False, **fields) -> None:
    """Structured logging entry point: `message` is the short human
    summary, `fields` are this line's structured extras (action,
    entity_id, duration_ms, error_code, ...) on top of the
    request_id/user_id/organisation_id the formatter always injects
    (docs/modules/logging_request_tracing.md #3). Prefer this over
    building an f-string by hand, so structured fields stay queryable
    instead of buried in free text. `exc_info=True` attaches the current
    exception's stack trace (server-side only -- docs/modules/logging_request_tracing.md
    #6); it's a real logging.Logger.log() parameter, not a structured
    field, so it must stay out of **fields or the stack trace would
    silently never be captured."""
    logger.log(level, message, exc_info=exc_info, extra={"fields": fields})
