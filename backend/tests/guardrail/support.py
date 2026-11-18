"""Fixed clock and a compact view of `extract` shared by the guardrail example tests."""

import datetime

from frontdesk.guardrail import Fact, extract

# A Tuesday, so the weekday expectations in the tests can be checked on a calendar.
TODAY = datetime.date(2026, 11, 17)


def read(text: str) -> list[tuple[str, tuple[Fact, ...]]]:
    return [(found.text, found.candidates) for found in extract(text, today=TODAY)]
