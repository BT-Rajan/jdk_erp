import re

_UPPERCASE_RE = re.compile(r"[A-Z]")
_DIGIT_RE = re.compile(r"[0-9]")
_SPECIAL_RE = re.compile(r"[^A-Za-z0-9]")


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
