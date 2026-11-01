"""
Date and Time Utilities for Bangladesh Standard Time (BST, UTC+6).
Ensures all system dates, audit logs, and timestamps are rendered in local BST.
"""

from datetime import datetime, timezone, timedelta
from typing import Any

try:
    from zoneinfo import ZoneInfo
    DHAKA_TZ = ZoneInfo("Asia/Dhaka")
except Exception:
    DHAKA_TZ = timezone(timedelta(hours=6))


def to_bst(val: Any) -> datetime | None:
    """Convert any naive or aware datetime into a Bangladesh Standard Time (UTC+6) datetime."""
    if val is None:
        return None
    if isinstance(val, str):
        val = val.strip()
        if not val:
            return None
        try:
            val = datetime.fromisoformat(val)
        except Exception:
            return None
    if not isinstance(val, datetime):
        return None

    if val.tzinfo is None:
        # Naive datetime from PostgreSQL / Python represents UTC
        val = val.replace(tzinfo=timezone.utc)
    return val.astimezone(DHAKA_TZ)


def format_datetime_bst(val: Any, fmt: str = "%b %d, %Y at %I:%M %p BST") -> str:
    """Format datetime into BST string with customizable format."""
    bst_dt = to_bst(val)
    if bst_dt is None:
        return "—"
    return bst_dt.strftime(fmt)


def format_date_bst(val: Any, fmt: str = "%b %d, %Y") -> str:
    """Format date into BST string."""
    bst_dt = to_bst(val)
    if bst_dt is None:
        return "—"
    return bst_dt.strftime(fmt)


def format_time_bst(val: Any, fmt: str = "%I:%M %p BST") -> str:
    """Format time into BST string."""
    bst_dt = to_bst(val)
    if bst_dt is None:
        return "—"
    return bst_dt.strftime(fmt)
