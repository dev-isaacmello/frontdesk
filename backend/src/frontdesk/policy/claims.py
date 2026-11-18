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
        r"|alterad[oa]s?|mudad[oa]s?|transferid[oa]s?)\b",
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


# "Até 10 minutos depois do horário marcado" states a rule about a booked time and says
# nothing was booked. Only this shape is let through: "te espero no horário marcado" still
# tells the customer that a booking exists.
_RELATIVE_TO_A_BOOKED_TIME = re.compile(
    r"\b(?:antes|depois|após)\s+(?:d?[oa]s?\s+)?(?:hor[áa]rios?|horas?)\s+"
    r"(?:marcad|agendad|reservad|combinad)[oa]s?\b",
    re.IGNORECASE,
)


def claims(reply: str) -> dict[Action, str]:
    """The actions the reply says were done, each with the word that says it."""
    read = _RELATIVE_TO_A_BOOKED_TIME.sub(" ", reply)
    found: dict[Action, str] = {}
    for action, pattern in _CLAIMS.items():
        match = next(affirmed(pattern, read), None)
        if match:
            found[action] = match.group(0)
    return found


def claimed_actions(reply: str) -> set[Action]:
    return set(claims(reply))


def unbacked_claims(reply: str, effects: Iterable[str]) -> dict[Action, str]:
    """The actions the reply claims that no tool of the turn performed, with the claiming word."""
    done = set(effects)
    return {
        action: word for action, word in claims(reply).items() if not (_BACKED_BY[action] & done)
    }
