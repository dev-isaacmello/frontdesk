"""Reads the money, times, dates, durations and counts written in a pt-BR text.

The text is scanned left to right; at each token the readers below try the longest expression
that starts there, so one piece of text yields one value with every reading it can have.
"""

import datetime
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from frontdesk.guardrail import vocabulary
from frontdesk.guardrail.cardinals import Cardinal, read_cardinal
from frontdesk.guardrail.dates import (
    next_day_and_month,
    next_day_of_month,
    next_weekday,
    valid_date,
)
from frontdesk.guardrail.facts import (
    Count,
    Day,
    Duration,
    Fact,
    Found,
    Money,
    Origin,
    Sourced,
    TimeOfDay,
)
from frontdesk.guardrail.lexer import Token, is_glued, symbol_at, tokenize, word_at, words_at

type _Tokens = Sequence[Token]
type _Facts = tuple[Fact, ...]

# A numeric expression with no exact typed value: it is reported so the reply gets blocked.
_UNTYPED: _Facts = ()

_CLOCK = re.compile(r"(?P<hour>[0-9]{1,2}):(?P<minute>[0-9]{2})")
_DATE = re.compile(r"(?P<day>[0-9]{1,2})/(?P<month>[0-9]{1,2})(?:/(?P<year>[0-9]{2}|[0-9]{4}))?")
_DECIMAL = re.compile(
    r"(?P<whole>[0-9]{1,15}|[0-9]{1,3}(?:\.[0-9]{3}){1,4}),(?P<fraction>[0-9]{1,2})"
)
_YEAR = re.compile(r"[0-9]{4}")
# What is glued to the hour in "14h30", "14h30min".
_COMPACT_MINUTES = re.compile(r"h(?P<minute>[0-9]{2})(?:min|m)?")

_CENTURY = 2000
_LAST_HOUR = 23
_LAST_MINUTE = 59
_LAST_DAY_OF_MONTH = 31
_MEASURE_UNITS = (
    vocabulary.REAL_UNITS | vocabulary.CENT_UNITS | vocabulary.HOUR_UNITS | vocabulary.MINUTE_UNITS
)


@dataclass(frozen=True)
class _Reading:
    end: int  # index of the first token after the value
    candidates: _Facts


@dataclass(frozen=True)
class _MinutesTail:
    minute: int
    end: int
    is_half: bool


def extract(text: str, *, today: datetime.date) -> list[Found]:
    """Every value written in `text`, in order, each with all the readings it can have."""
    tokens = tokenize(text)
    found: list[Found] = []
    index = 0
    while index < len(tokens):
        reading = _read(tokens, index, today)
        if reading is None:
            index += 1
            continue
        start, end = tokens[index].start, tokens[reading.end - 1].end
        found.append(Found(text[start:end], start, end, reading.candidates))
        index = reading.end
    return found


def facts_in(text: str, origin: Origin, *, today: datetime.date) -> list[Sourced]:
    """Every reading of every value in `text`, tagged with where the text came from."""
    return [
        Sourced(candidate, origin)
        for found in extract(text, today=today)
        for candidate in found.candidates
    ]


def _read(tokens: _Tokens, index: int, today: datetime.date) -> _Reading | None:
    kind = tokens[index].kind
    if kind == "opaque":
        return _Reading(index + 1, _UNTYPED)
    if kind == "number":
        return _read_numeral(tokens, index, today)
    if kind == "word":
        return (
            _read_currency(tokens, index)
            or _read_named_day(tokens, index, today)
            or _read_named_time(tokens, index)
            or _read_fixed_duration(tokens, index)
            or _read_first_of_month(tokens, index, today)
            or _read_number(tokens, index, today)
        )
    return None


def _read_numeral(tokens: _Tokens, index: int, today: datetime.date) -> _Reading:
    """A token of digits: its shape says whether it is a clock, a date, a decimal or a number."""
    text = tokens[index].text
    if clock := _CLOCK.fullmatch(text):
        return _read_clock(tokens, index, int(clock["hour"]), int(clock["minute"]))
    if written := _DATE.fullmatch(text):
        return _Reading(index + 1, _days(_numeric_date(written, today)))
    if decimal := _DECIMAL.fullmatch(text):
        return _read_decimal(tokens, index, _cents(decimal))
    return _read_number(tokens, index, today) or _Reading(index + 1, _UNTYPED)


def _read_number(tokens: _Tokens, index: int, today: datetime.date) -> _Reading | None:
    """A whole number in digits or words, typed by the unit or the context around it."""
    cardinal = read_cardinal(tokens, index)
    if cardinal is None:
        return None
    reading = (
        _read_inexact(tokens, cardinal)
        or _read_month_date(tokens, cardinal, today)
        or _read_money(tokens, cardinal)
        or _read_hours(tokens, index, cardinal)
        or _read_minutes(tokens, cardinal)
        or _read_day_of_month(tokens, index, cardinal, today)
        or _read_bare_hour(tokens, index, cardinal)
        or _read_glued_suffix(tokens, cardinal)
    )
    if reading is not None or cardinal.is_article:
        return reading
    return _Reading(cardinal.end, (Count(cardinal.value),))


# Values that cannot be typed ------------------------------------------------------------------


def _inexact_end(tokens: _Tokens, index: int) -> int | None:
    """Where a tail that makes the number before it inexact ends: "%", "milhões", "e poucos"."""
    if symbol_at(tokens, index) == "%":
        return index + 1
    if words_at(tokens, index, vocabulary.PERCENT_WORDS):
        return index + len(vocabulary.PERCENT_WORDS)
    if word_at(tokens, index) in vocabulary.LARGE_MAGNITUDES:
        return index + 1
    if word_at(tokens, index) != vocabulary.AND:
        return None
    tail = word_at(tokens, index + 1)
    if tail == vocabulary.MASCULINE_HALF:
        return index + 2
    if tail not in vocabulary.VAGUE_AMOUNTS:
        return None
    has_unit = word_at(tokens, index + 2) in _MEASURE_UNITS
    return index + 3 if has_unit else index + 2


def _read_inexact(tokens: _Tokens, cardinal: Cardinal) -> _Reading | None:
    end = _inexact_end(tokens, cardinal.end)
    return None if end is None else _Reading(end, _UNTYPED)


def _read_glued_suffix(tokens: _Tokens, cardinal: Cardinal) -> _Reading | None:
    """Digits touching letters that are no known unit ("3kg", "1º") have no exact type."""
    end = cardinal.end
    if not is_glued(tokens, end) or tokens[end - 1].kind != "number":
        return None
    suffix = tokens[end]
    if suffix.kind == "word" and suffix.text == vocabulary.TIMES_SUFFIX:
        return _Reading(end + 1, (Count(cardinal.value),))
    if suffix.kind == "word" or suffix.text in vocabulary.ORDINAL_MARKS:
        return _Reading(end + 1, _UNTYPED)
    return None


# Money ----------------------------------------------------------------------------------------


def _cents(decimal: re.Match[str]) -> int:
    whole = int(decimal["whole"].replace(".", ""))
    return whole * 100 + int(decimal["fraction"].ljust(2, "0"))


def _read_currency(tokens: _Tokens, index: int) -> _Reading | None:
    """`R$` and the amount after it."""
    has_sign = (
        tokens[index].text == "r"
        and symbol_at(tokens, index + 1) == "$"
        and is_glued(tokens, index + 1)
    )
    amount = index + 2
    if not has_sign or amount >= len(tokens) or tokens[amount].kind != "number":
        return None
    if decimal := _DECIMAL.fullmatch(tokens[amount].text):
        return _close_currency(tokens, amount + 1, _cents(decimal))
    cardinal = read_cardinal(tokens, amount)
    if cardinal is None:
        return _Reading(amount + 1, _UNTYPED)
    return _close_currency(tokens, cardinal.end, cardinal.value * 100)


def _close_currency(tokens: _Tokens, end: int, cents: int) -> _Reading:
    inexact = _inexact_end(tokens, end)
    if inexact is not None:
        return _Reading(inexact, _UNTYPED)
    # "R$ 1,5 mil": the multiplier applies to a fraction, which no reader here turns into cents.
    if word_at(tokens, end) == vocabulary.THOUSAND:
        return _Reading(end + 1, _UNTYPED)
    if word_at(tokens, end) in vocabulary.REAL_UNITS:
        end += 1
    return _Reading(end, (Money(cents),))


def _read_decimal(tokens: _Tokens, index: int, cents: int) -> _Reading:
    """A number with a decimal comma is money only when "reais" follows it."""
    end = index + 1
    inexact = _inexact_end(tokens, end)
    if inexact is not None:
        return _Reading(inexact, _UNTYPED)
    if word_at(tokens, end) in vocabulary.REAL_UNITS:
        return _Reading(end + 1, (Money(cents),))
    return _Reading(end, _UNTYPED)


def _read_money(tokens: _Tokens, cardinal: Cardinal) -> _Reading | None:
    unit = word_at(tokens, cardinal.end)
    if unit in vocabulary.CENT_UNITS:
        return _Reading(cardinal.end + 1, (Money(cardinal.value),))
    if unit not in vocabulary.REAL_UNITS:
        return None
    end = cardinal.end + 1
    centavos = _read_centavos_tail(tokens, end)
    if centavos is None:
        return _Reading(end, (Money(cardinal.value * 100),))
    return _Reading(centavos.end, (Money(cardinal.value * 100 + centavos.value),))


def _read_centavos_tail(tokens: _Tokens, index: int) -> Cardinal | None:
    """The "e 50 centavos" that completes an amount in reais."""
    if word_at(tokens, index) != vocabulary.AND:
        return None
    centavos = read_cardinal(tokens, index + 1)
    if centavos is None or centavos.value >= 100:
        return None
    if word_at(tokens, centavos.end) not in vocabulary.CENT_UNITS:
        return None
    return Cardinal(centavos.value, centavos.end + 1)


# Time of day and duration ---------------------------------------------------------------------


def _times(hour: int | None, minute: int) -> _Facts:
    if hour is None or not (0 <= hour <= _LAST_HOUR and 0 <= minute <= _LAST_MINUTE):
        return _UNTYPED
    return (TimeOfDay(hour, minute),)


def _time_context(tokens: _Tokens, index: int) -> Literal["certain", "possible"] | None:
    """Whether the word before the value introduces a time of day."""
    if index == 0 or tokens[index - 1].kind != "word":
        return None
    previous = tokens[index - 1]
    if previous.accented:
        if previous.text == vocabulary.TIME_PREPOSITION:
            return "certain"
        return "possible" if previous.text == vocabulary.ACCENTED_LOOSE_TIME_PREPOSITION else None
    return "possible" if previous.text in vocabulary.LOOSE_TIME_PREPOSITIONS else None


def _is_duration_context(tokens: _Tokens, index: int, end: int) -> bool:
    """Whether the words around tokens[index:end] say it is a length of time."""
    return word_at(tokens, index - 1) in vocabulary.DURATION_LEADS or words_at(
        tokens, end, vocabulary.DURATION_TAIL
    )


def _read_minutes_tail(tokens: _Tokens, index: int, *, needs_unit: bool) -> _MinutesTail | None:
    """The minutes joined to an hour by "e": "e meia", "e quinze", "e 30 minutos"."""
    if word_at(tokens, index) != vocabulary.AND:
        return None
    if word_at(tokens, index + 1) == vocabulary.HALF:
        return _MinutesTail(30, index + 2, is_half=True)
    minutes = read_cardinal(tokens, index + 1)
    if minutes is None or not 1 <= minutes.value <= _LAST_MINUTE:
        return None
    if word_at(tokens, minutes.end) in vocabulary.MINUTE_UNITS:
        return _MinutesTail(minutes.value, minutes.end + 1, is_half=False)
    if needs_unit:
        return None
    return _MinutesTail(minutes.value, minutes.end, is_half=False)


def _read_period(tokens: _Tokens, index: int, hour: int, minute: int) -> _Reading | None:
    """An hour followed by "da manhã", "da tarde", "da noite": only a time, on a 24-hour clock."""
    period = word_at(tokens, index + 1)
    if word_at(tokens, index) != vocabulary.PERIOD_LINK or period is None:
        return None
    clock_hours = vocabulary.PERIOD_CLOCK_HOURS.get(period)
    if clock_hours is None:
        return None
    return _Reading(index + 2, _times(clock_hours.get(hour), minute))


def _read_clock(tokens: _Tokens, index: int, hour: int, minute: int) -> _Reading:
    """`14:30`, which is never a duration."""
    end = index + 1
    if word_at(tokens, end) in vocabulary.HOUR_UNITS:
        end += 1
    return _read_period(tokens, end, hour, minute) or _Reading(end, _times(hour, minute))


def _read_hours(tokens: _Tokens, index: int, cardinal: Cardinal) -> _Reading | None:
    """A number with an hour unit: "14h", "14h30", "2 horas", "uma hora e meia"."""
    unit = word_at(tokens, cardinal.end)
    end = cardinal.end + 1
    minute = 0
    if unit in vocabulary.HOUR_UNITS:
        tail = _read_minutes_tail(tokens, end, needs_unit=True)
        if tail is not None:
            minute, end = tail.minute, tail.end
    elif unit is not None and is_glued(tokens, cardinal.end):
        compact = _COMPACT_MINUTES.fullmatch(unit)
        if compact is None:
            return None
        minute = int(compact["minute"])
    else:
        return None
    if minute > _LAST_MINUTE:
        return _Reading(end, _UNTYPED)
    return _read_period(tokens, end, cardinal.value, minute) or _Reading(
        end, _hour_candidates(tokens, index, end, cardinal.value, minute)
    )


def _hour_candidates(tokens: _Tokens, index: int, end: int, hour: int, minute: int) -> _Facts:
    """Hours are a duration or a time of day unless the words around them settle it."""
    time = _times(hour, minute)
    duration: _Facts = (Duration(hour * 60 + minute),)
    if time and _time_context(tokens, index) == "certain":
        return time
    if _is_duration_context(tokens, index, end):
        return duration
    return duration + time


def _read_minutes(tokens: _Tokens, cardinal: Cardinal) -> _Reading | None:
    if word_at(tokens, cardinal.end) not in vocabulary.MINUTE_UNITS:
        return None
    return _Reading(cardinal.end + 1, (Duration(cardinal.value),))


def _read_bare_hour(tokens: _Tokens, index: int, cardinal: Cardinal) -> _Reading | None:
    """A number without unit that a preposition, a period of the day or "e meia" makes a time."""
    context = _time_context(tokens, index)
    tail = _read_minutes_tail(tokens, cardinal.end, needs_unit=False)
    if tail is not None and not (context or tail.is_half or _has_period(tokens, tail.end)):
        # "dez e quinze" with nothing around it is two numbers, not a quarter past ten.
        tail = None
    minute, end = (tail.minute, tail.end) if tail else (0, cardinal.end)
    with_period = _read_period(tokens, end, cardinal.value, minute)
    if with_period is not None:
        return with_period
    time = _times(cardinal.value, minute)
    if not time:
        return None
    if tail is not None:
        return _Reading(end, time)
    if context is None or cardinal.is_article:
        return None
    if context == "certain":
        return _Reading(end, time)
    return _Reading(end, (*time, Count(cardinal.value)))


def _has_period(tokens: _Tokens, index: int) -> bool:
    return _read_period(tokens, index, 0, 0) is not None


def _read_named_time(tokens: _Tokens, index: int) -> _Reading | None:
    """Noon and midnight by name, with the half hour or the minutes that may follow."""
    for phrase, hour in vocabulary.NAMED_TIMES.items():
        if words_at(tokens, index, phrase):
            end = index + len(phrase)
            tail = _read_minutes_tail(tokens, end, needs_unit=True)
            if tail is None:
                return _Reading(end, (TimeOfDay(hour, 0),))
            return _Reading(tail.end, (TimeOfDay(hour, tail.minute),))
    return None


def _read_fixed_duration(tokens: _Tokens, index: int) -> _Reading | None:
    for phrase, minutes in vocabulary.FIXED_DURATIONS.items():
        if words_at(tokens, index, phrase):
            return _Reading(index + len(phrase), (Duration(minutes),))
    return None


# Days -----------------------------------------------------------------------------------------


def _days(date: datetime.date | None) -> _Facts:
    return _UNTYPED if date is None else (Day(date),)


def _numeric_date(written: re.Match[str], today: datetime.date) -> datetime.date | None:
    """`20/11` is the nearest such day from today on; with a year it is that exact date."""
    day, month, year = int(written["day"]), int(written["month"]), written["year"]
    if year is None:
        return next_day_and_month(today, month, day)
    century = _CENTURY if len(year) == 2 else 0
    return valid_date(century + int(year), month, day)


def _read_named_day(tokens: _Tokens, index: int, today: datetime.date) -> _Reading | None:
    """Days by name: "hoje", "amanhã", "depois de amanhã" and the weekdays."""
    word = tokens[index].text
    if words_at(tokens, index, vocabulary.DAY_AFTER_TOMORROW):
        end = index + len(vocabulary.DAY_AFTER_TOMORROW)
        return _Reading(end, (Day(today + datetime.timedelta(days=2)),))
    if word in vocabulary.RELATIVE_DAYS:
        offset = datetime.timedelta(days=vocabulary.RELATIVE_DAYS[word])
        return _Reading(index + 1, (Day(today + offset),))
    if word not in vocabulary.WEEKDAYS:
        return None
    has_suffix = word_at(tokens, index + 1) in vocabulary.WEEKDAY_SUFFIX_WORDS
    end = index + 2 if has_suffix else index + 1
    return _Reading(end, _weekday_candidates(tokens, index, end, vocabulary.WEEKDAYS[word], today))


def _weekday_candidates(
    tokens: _Tokens, index: int, end: int, weekday: int, today: datetime.date
) -> _Facts:
    nearest = next_weekday(today, weekday)
    if weekday == today.weekday() and _follows_today(tokens, index):
        return (Day(today),)
    if _means_next_week(tokens, index, end):
        return (Day(nearest), Day(nearest + datetime.timedelta(days=7)))
    return (Day(nearest),)


def _follows_today(tokens: _Tokens, index: int) -> bool:
    """Whether the weekday at `index` names today: "hoje, sexta", "hoje (sexta)", "hoje é sexta"."""
    before = index - 1
    is_verb = word_at(tokens, before) == vocabulary.TODAY_LINK_VERB and tokens[before].accented
    if is_verb or symbol_at(tokens, before) in vocabulary.TODAY_LINK_SYMBOLS:
        before -= 1
    return word_at(tokens, before) == vocabulary.TODAY


def _means_next_week(tokens: _Tokens, index: int, end: int) -> bool:
    """Whether it is said as "próxima sexta" or "sexta que vem", which may skip this week."""
    if word_at(tokens, index - 1) in vocabulary.NEXT_WEEK_LEADS:
        return True
    return any(words_at(tokens, end, tail) for tail in vocabulary.NEXT_WEEK_TAILS)


def _after_ordinal_mark(tokens: _Tokens, cardinal: Cardinal) -> int:
    """Skip the mark of "1º", the usual way to write the first day of a month."""
    end = cardinal.end
    if cardinal.value != 1 or not is_glued(tokens, end):
        return end
    return end + 1 if tokens[end].text in vocabulary.ORDINAL_MARKS else end


def _read_month_date(tokens: _Tokens, cardinal: Cardinal, today: datetime.date) -> _Reading | None:
    """`20 de novembro`, optionally followed by `de 2026`."""
    link = _after_ordinal_mark(tokens, cardinal)
    month = vocabulary.MONTHS.get(word_at(tokens, link + 1) or "")
    if word_at(tokens, link) != vocabulary.MONTH_LINK or month is None:
        return None
    end = link + 2
    year = _read_year(tokens, end)
    if year is None:
        return _Reading(end, _days(next_day_and_month(today, month, cardinal.value)))
    return _Reading(end + 2, _days(valid_date(year, month, cardinal.value)))


def _read_year(tokens: _Tokens, index: int) -> int | None:
    if word_at(tokens, index) != vocabulary.MONTH_LINK or index + 1 >= len(tokens):
        return None
    year = tokens[index + 1]
    if year.kind != "number" or not _YEAR.fullmatch(year.text):
        return None
    return int(year.text)


def _read_day_of_month(
    tokens: _Tokens, index: int, cardinal: Cardinal, today: datetime.date
) -> _Reading | None:
    """A number right after "dia": the nearest day of the month from today on."""
    if cardinal.is_article or word_at(tokens, index - 1) not in vocabulary.DAY_OF_MONTH_LEADS:
        return None
    if not 1 <= cardinal.value <= _LAST_DAY_OF_MONTH:
        return None
    date = next_day_of_month(today, cardinal.value)
    return None if date is None else _Reading(_after_ordinal_mark(tokens, cardinal), (Day(date),))


def _read_first_of_month(tokens: _Tokens, index: int, today: datetime.date) -> _Reading | None:
    """The word "primeiro" is a date only inside one: "primeiro de maio", "dia primeiro"."""
    if tokens[index].text != vocabulary.FIRST:
        return None
    first = Cardinal(1, index + 1)
    return _read_month_date(tokens, first, today) or _read_day_of_month(tokens, index, first, today)
