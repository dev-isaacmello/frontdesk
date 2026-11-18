"""Typed values a reply can state, and the records that tie each one to where it came from."""

import datetime
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Money:
    cents: int


@dataclass(frozen=True)
class TimeOfDay:
    hour: int
    minute: int


@dataclass(frozen=True)
class Day:
    date: datetime.date


@dataclass(frozen=True)
class Duration:
    minutes: int


@dataclass(frozen=True)
class Count:
    value: int


type Fact = Money | TimeOfDay | Day | Duration | Count
type Origin = Literal["tool", "customer", "profile", "rules", "knowledge"]


@dataclass(frozen=True)
class Sourced:
    fact: Fact
    origin: Origin


@dataclass(frozen=True)
class Found:
    """A value read in a text; no candidates means it is numeric but could not be typed."""

    text: str
    start: int
    end: int
    candidates: tuple[Fact, ...]


@dataclass(frozen=True)
class Violation:
    text: str
    reason: Literal["untyped", "no_origin"]
    candidates: tuple[Fact, ...]


@dataclass(frozen=True)
class Verdict:
    violations: tuple[Violation, ...]

    @property
    def passed(self) -> bool:
        return not self.violations
