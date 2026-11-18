"""GRD-6: a reply says something was booked, changed or cancelled only if a tool did it."""

import re
from collections.abc import Iterable
from typing import Literal

from frontdesk.policy.sentences import affirmed

type Action = Literal["booked", "cancelled", "rescheduled"]

# Past and finished forms only. "Quer que eu agende?" and "posso cancelar" offer an action
# and claim nothing.
_CLAIMS: dict[Action, re.Pattern[str]] = {
    "booked": re.compile(
        r"\b(?:agendei|marquei|reservei|confirmei|agendad[oa]s?|marcad[oa]s?|reservad[oa]s?"
        r"|confirmad[oa]s?)\b",
        re.IGNORECASE,
    ),
    "cancelled": re.compile(
        r"\b(?:cancelei|desmarquei|cancelad[oa]s?|desmarcad[oa]s?)\b", re.IGNORECASE
    ),
    "rescheduled": re.compile(
        r"\b(?:remarquei|reagendei|alterei|mudei|transferi|remarcad[oa]s?|reagendad[oa]s?"
        r"|alterad[oa]s?)\b",
        re.IGNORECASE,
    ),
}

# What a tool has to have done in the turn for the claim to stand. A booking that the
# tools listed exists, so calling it "agendado" is true without a write in this turn.
_BACKED_BY: dict[Action, frozenset[str]] = {
    "booked": frozenset({"booked", "rescheduled", "listed"}),
    "cancelled": frozenset({"cancelled"}),
    "rescheduled": frozenset({"rescheduled"}),
}


def claimed_actions(reply: str) -> set[Action]:
    return {action for action, pattern in _CLAIMS.items() if next(affirmed(pattern, reply), None)}


def unbacked_claims(reply: str, effects: Iterable[str]) -> set[Action]:
    """The actions the reply claims that no tool of the turn performed."""
    done = set(effects)
    return {action for action in claimed_actions(reply) if not (_BACKED_BY[action] & done)}
