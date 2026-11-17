"""Conversions between the tenant's wall clock and UTC."""

from datetime import datetime
from zoneinfo import ZoneInfo


def to_local(moment: datetime, timezone: ZoneInfo) -> datetime:
    """Reads a naive datetime as the tenant's wall clock and converts an aware one to it."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone)
    return moment.astimezone(timezone)
