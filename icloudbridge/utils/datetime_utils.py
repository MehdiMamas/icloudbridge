"""Datetime utility helpers."""

from __future__ import annotations

from datetime import datetime, timezone, tzinfo
from zoneinfo import ZoneInfo

# Safe timestamp bounds (year 1970 to year 3000)
MIN_TIMESTAMP = 0
MAX_TIMESTAMP = 32503680000  # 3000-01-01 00:00:00 UTC


def safe_fromtimestamp(timestamp: float | None, tz=None) -> datetime | None:
    """Convert timestamp to datetime with bounds checking.

    Args:
        timestamp: Unix timestamp to convert
        tz: Optional timezone info to attach to the result

    Returns:
        datetime object if conversion successful, None if timestamp is
        None, out of bounds, or conversion fails
    """
    if timestamp is None:
        return None
    try:
        if not (MIN_TIMESTAMP <= timestamp <= MAX_TIMESTAMP):
            return None
        return datetime.fromtimestamp(timestamp, tz=tz) if tz else datetime.fromtimestamp(timestamp)
    except (OSError, OverflowError, ValueError):
        return None


def local_timezone() -> tzinfo:
    """The Mac's time zone, with its daylight saving rules."""
    try:
        from Foundation import NSTimeZone

        return ZoneInfo(NSTimeZone.localTimeZone().name())
    except Exception:
        # No IANA name to go by: today's offset is the best there is
        return datetime.now().astimezone().tzinfo
