"""Shared clock semantics for tracker business dates and audit timestamps."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE_NAME = "Europe/Belgrade"
BUSINESS_TIMEZONE = ZoneInfo(BUSINESS_TIMEZONE_NAME)


def utc_instant(value=None):
    """Return an aware UTC datetime, accepting an injected instant for tests."""
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("clock instant must include timezone information")
    return current.astimezone(timezone.utc)


def utc_timestamp(value=None):
    """Return a second-precision ISO-8601 UTC audit timestamp."""
    return utc_instant(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def business_date(value=None):
    """Return the Europe/Belgrade calendar date for an instant."""
    return utc_instant(value).astimezone(BUSINESS_TIMEZONE).date()
