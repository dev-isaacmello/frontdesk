"""Reads a whole number written in digits or in pt-BR words from a run of tokens."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from frontdesk.guardrail.lexer import Token, word_at
from frontdesk.guardrail.vocabulary import AND, ARTICLES, HUNDREDS, TEENS, TENS, THOUSAND, UNITS

# Plain digits, or groups of three split by the Brazilian thousands dot ("1.200"). The length
# is capped because a longer run is an identifier, not a quantity anyone states in a reply.
_INTEGER = re.compile(r"[0-9]{1,15}|[0-9]{1,3}(?:\.[0-9]{3}){1,4}")


@dataclass(frozen=True)
class Cardinal:
    value: int
    end: int  # index of the first token after the number
    is_article: bool = False  # only "um"/"uma", which is a number just next to a unit


def read_cardinal(tokens: Sequence[Token], index: int) -> Cardinal | None:
    """Read the longest whole number that starts at `index`."""
    lead = _read_digits(tokens, index) or _read_below_thousand(tokens, index)
    if lead is not None and word_at(tokens, lead.end) == THOUSAND:
        return _read_after_thousand(tokens, lead.value * 1000, lead.end + 1)
    if lead is None and word_at(tokens, index) == THOUSAND:
        return _read_after_thousand(tokens, 1000, index + 1)
    return lead


def _read_digits(tokens: Sequence[Token], index: int) -> Cardinal | None:
    if index >= len(tokens) or tokens[index].kind != "number":
        return None
    if not _INTEGER.fullmatch(tokens[index].text):
        return None
    return Cardinal(int(tokens[index].text.replace(".", "")), index + 1)


def _read_after_thousand(tokens: Sequence[Token], thousands: int, index: int) -> Cardinal:
    """Add what follows "mil": "mil e duzentos", "dois mil trezentos e dez"."""
    start = index + 1 if word_at(tokens, index) == AND else index
    rest = _read_below_thousand(tokens, start)
    if rest is None:
        return Cardinal(thousands, index)
    return Cardinal(thousands + rest.value, rest.end)


def _read_below_thousand(tokens: Sequence[Token], index: int) -> Cardinal | None:
    word = word_at(tokens, index)
    if word not in HUNDREDS:
        return _read_below_hundred(tokens, index)
    hundreds = Cardinal(HUNDREDS[word], index + 1)
    if word_at(tokens, hundreds.end) != AND:
        return hundreds
    rest = _read_below_hundred(tokens, hundreds.end + 1)
    if rest is None:
        return hundreds
    return Cardinal(hundreds.value + rest.value, rest.end)


def _read_below_hundred(tokens: Sequence[Token], index: int) -> Cardinal | None:
    word = word_at(tokens, index)
    if word in TENS:
        unit = word_at(tokens, index + 2) if word_at(tokens, index + 1) == AND else None
        if unit in UNITS:
            return Cardinal(TENS[word] + UNITS[unit], index + 3)
        return Cardinal(TENS[word], index + 1)
    if word in TEENS:
        return Cardinal(TEENS[word], index + 1)
    if word in UNITS:
        return Cardinal(UNITS[word], index + 1, is_article=word in ARTICLES)
    return None
