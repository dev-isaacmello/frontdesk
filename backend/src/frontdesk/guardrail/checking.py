"""Decides whether every value stated in a reply is backed by the ledger of the turn."""

import datetime
from collections.abc import Iterable

from frontdesk.guardrail.extraction import extract
from frontdesk.guardrail.facts import Fact, Money, Origin, Sourced, Verdict, Violation

# A price is only trusted when a tool read it from the catalog; the other types may also be
# repeated back from what the customer, the profile, the owner rules or the knowledge base said.
_MONEY_ORIGINS: frozenset[Origin] = frozenset({"tool"})


def _is_allowed(sourced: Sourced) -> bool:
    return not isinstance(sourced.fact, Money) or sourced.origin in _MONEY_ORIGINS


def check(reply: str, ledger: Iterable[Sourced], *, today: datetime.date) -> Verdict:
    """Report, in order of appearance, each value of `reply` that the ledger does not back."""
    backed: set[Fact] = {sourced.fact for sourced in ledger if _is_allowed(sourced)}
    violations: list[Violation] = []
    for found in extract(reply, today=today):
        if not found.candidates:
            violations.append(Violation(found.text, "untyped", found.candidates))
        elif backed.isdisjoint(found.candidates):
            violations.append(Violation(found.text, "no_origin", found.candidates))
    return Verdict(tuple(violations))
