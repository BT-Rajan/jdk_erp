import re
from datetime import date, datetime

from email_validator import EmailNotValidError, validate_email

_UPPERCASE_RE = re.compile(r"[A-Z]")
_DIGIT_RE = re.compile(r"[0-9]")
_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_password_complexity(password: str) -> str:
    """The one password policy for the whole project (docs/modules/authentication.md #4).
    Raises ValueError with a user-facing message on the first rule broken."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if not _UPPERCASE_RE.search(password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not _DIGIT_RE.search(password):
        raise ValueError("Password must contain at least one number.")
    if not _SPECIAL_RE.search(password):
        raise ValueError("Password must contain at least one special character.")
    return password


def validate_key(value: str) -> str:
    """Shared free-form-string constraint: permissions' module_key/action
    (docs/modules/permissions.md #2) and audit_events' module/action
    (docs/modules/audit_trail.md #2) are both open-ended -- a future
    module registers a new one by writing a row, not editing a Python
    constant -- but still lowercase snake_case so 'Sales' and 'sales'
    can't silently become two different keys."""
    if not _KEY_RE.match(value):
        raise ValueError("must be lowercase snake_case, e.g. 'sales' or 'view'")
    return value


def check_max_length(value: str, max_length: int, field_label: str) -> str:
    """Enforces a field's DB column width at the API boundary, checked
    after whatever normalization (strip, case-fold, digit-extraction)
    the caller already applied -- so an over-limit value is rejected
    with a clear 422 instead of being silently truncated (SQLite, or
    MySQL outside strict mode) or raising a raw IntegrityError/DataError
    at the database layer (docs/modules/common_validation.md)."""
    if len(value) > max_length:
        raise ValueError(f"{field_label} must be at most {max_length} characters.")
    return value


def normalize_email(email: str) -> str:
    """One normalization for every place an email is stored or compared
    -- lowercase, trimmed -- so 'Ada@Example.com' and 'ada@example.com'
    can't silently become two different users or bypass a duplicate
    check (docs/modules/common_validation.md #1)."""
    return email.strip().lower()


def validate_email_format(email: str) -> str:
    """Format checking via the `email_validator` package already used by
    Pydantic's `EmailStr` (see app/schemas/user.py) -- reused here rather
    than duplicated as a hand-rolled regex, for the call sites (a future
    signup/user-creation flow) that need a plain callable rather than a
    Pydantic field type. Raises ValueError with a user-facing message;
    never leaks the library's own exception type/message verbatim."""
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise ValueError(f"'{email}' is not a valid email address.") from exc
    return normalize_email(email)


def validate_company_email_domain(email: str, allowed_domain: str | None) -> str:
    """Only the organisation's configured company domain is allowed --
    but the domain is configuration (Organisation.email_domain), not a
    hard-coded constant, so this takes it as a parameter rather than
    reading global settings. An organisation that hasn't configured one
    (allowed_domain is None) has no domain restriction at all."""
    if allowed_domain is None:
        return normalize_email(email)
    normalized = normalize_email(email)
    domain = normalized.rsplit("@", 1)[-1]
    if domain != allowed_domain.strip().lower():
        raise ValueError(f"Email must use the '{allowed_domain}' company domain.")
    return normalized


def validate_date_range(
    start: date | datetime,
    end: date | datetime,
    *,
    start_label: str = "Start date",
    end_label: str = "End date",
) -> None:
    """The one `from <= to` comparison mechanism (docs/modules/common_validation.md
    #2) -- equal dates are valid (same-day validity), only start > end is
    rejected. Whether past/future dates are allowed at all is a business
    rule the calling module enforces itself; this only orders the pair."""
    if start > end:
        raise ValueError(f"{start_label} must not be after {end_label}.")
