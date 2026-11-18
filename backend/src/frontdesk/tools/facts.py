"""Turns what a tool received and returned into typed facts for the numeric guardrail.

The walk is by type and by the naming of the fields, not per tool, so a field added to an
output cannot be forgotten here: an integer that ends in `_cents` is money, one that ends
in `_minutes` is a duration, any other integer is a count, and so is the length of a list.
"""

import datetime as dt
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from frontdesk.guardrail import Count, Day, Duration, Fact, Money, TimeOfDay


def facts_of(value: BaseModel, timezone: ZoneInfo) -> list[Fact]:
    """Every amount, time, date, duration and count in a tool input or output."""
    facts: list[Fact] = []
    _walk(None, value, timezone, facts)
    return facts


def _walk(name: str | None, value: object, timezone: ZoneInfo, facts: list[Fact]) -> None:
    if isinstance(value, BaseModel):
        for field in type(value).model_fields:
            _walk(field, getattr(value, field), timezone, facts)
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk(str(key), item, timezone, facts)
    elif isinstance(value, list | tuple):
        facts.append(Count(len(value)))
        for item in value:
            _walk(name, item, timezone, facts)
    elif isinstance(value, bool):
        return
    elif isinstance(value, int):
        facts.append(_number(name or "", value))
    elif isinstance(value, dt.datetime):
        # A time with an offset is converted; one without is already on the tenant's clock.
        local = value.astimezone(timezone) if value.tzinfo else value
        facts.append(Day(local.date()))
        facts.append(TimeOfDay(local.hour, local.minute))
    elif isinstance(value, dt.date):
        facts.append(Day(value))
    elif isinstance(value, dt.time):
        facts.append(TimeOfDay(value.hour, value.minute))


def _number(name: str, value: int) -> Fact:
    if name.endswith("_cents"):
        return Money(value)
    if name.endswith("_minutes"):
        return Duration(value)
    return Count(value)
