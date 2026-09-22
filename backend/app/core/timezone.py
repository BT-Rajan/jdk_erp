from datetime import datetime, UTC
from zoneinfo import ZoneInfo

JDK_TIMEZONE = ZoneInfo("Asia/Kuwait")


def now_jdk() -> datetime:
    """The current time in JDK/Kuwait local time -- for display, never
    for storage (every timestamp column in this project stays UTC)."""
    return datetime.now(JDK_TIMEZONE)


def to_jdk_time(value: datetime) -> datetime:
    """Converts an aware datetime to JDK/Kuwait time, or attaches UTC
    to a naive one first (every existing timestamp column in this
    project is naive-but-UTC) before converting. The one place this
    conversion happens -- no module implements its own
    (docs/modules/common_validation.md #3)."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(JDK_TIMEZONE)
