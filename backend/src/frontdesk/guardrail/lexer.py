"""Splits a pt-BR text into tokens compared without case or accents, positioned in the original."""

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from frontdesk.guardrail.vocabulary import COMPOUND_WORDS

type TokenKind = Literal["number", "word", "symbol", "opaque"]
_KINDS: tuple[TokenKind, ...] = ("number", "word", "symbol", "opaque")


@dataclass(frozen=True)
class Token:
    """A piece of the text; `opaque` is a digit sequence that is known to have no typed value."""

    kind: TokenKind
    text: str  # lowercase, without accents
    start: int  # span in the original text
    end: int
    accented: bool


_HYPHENS = frozenset("\N{HYPHEN}\N{NON-BREAKING HYPHEN}")
_COMBINING_CATEGORIES = frozenset({"Mn", "Mc", "Me"})

_TOKEN = re.compile(
    r"""
      (?P<opaque>
          (?: \+? [0-9]{2} [ ]? )?                       # country code
          (?: \( [0-9]{2} \) [ ]? | [0-9]{2} [ ] )?      # area code
          (?: 9 [ ] )?
          [0-9]{4,5} - [0-9]{4} (?! [0-9] )              # the phone number itself
        | [¼-¾⅐-⅞]                   # fraction glyphs such as one half
      )
    | (?P<number> [0-9]+ (?: [.,:/-] [0-9]+ )* )         # digits joined by single separators
    | (?P<word>   [^\W\d_] [^\W_]* )                     # letters first, so "A1" is one word
    | (?P<symbol> \S )
    """,
    re.VERBOSE,
)
# "1." or "2)" opening a line that goes on, optionally wrapped in chat bold or italic marks.
_LIST_MARKER = re.compile(
    r"^[ ]*[*_]{0,2}(?P<number>[0-9]{1,3})[.)][*_]{0,2}(?=[ ]+\S)", re.MULTILINE
)


def _fold_char(char: str) -> str:
    """The single comparable character for `char`, or nothing for a combining mark."""
    if unicodedata.category(char) in _COMBINING_CATEGORIES:
        return ""
    if char in _HYPHENS:
        return "-"
    if char.isspace():
        return "\n" if char == "\n" else " "
    if char.isdecimal():
        return str(unicodedata.decimal(char))
    base = unicodedata.normalize("NFD", char)[0]
    return base.lower()[:1] or base


def _fold(text: str) -> tuple[str, list[int]]:
    """Fold `text` and return, for each folded character, its index in the original."""
    chars: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(text):
        folded = _fold_char(char)
        if folded:
            chars.append(folded)
            offsets.append(index)
    offsets.append(len(text))
    return "".join(chars), offsets


def _blank_list_markers(folded: str) -> str:
    """Erase "1.", "2)", ... while they count up from one; "45. " opening a line stays a value."""
    chars = list(folded)
    expected = 1
    for marker in _LIST_MARKER.finditer(folded):
        number = int(marker["number"])
        if number not in (1, expected):
            continue
        expected = number + 1
        chars[marker.start() : marker.end()] = " " * len(marker.group())
    return "".join(chars)


def _compound_at(tokens: Sequence[Token], index: int) -> Token | None:
    """The hyphenated word the vocabulary knows that starts at `index`, as a single token."""
    if index + 2 >= len(tokens):
        return None
    first, hyphen, last = tokens[index : index + 3]
    is_one_run = first.end == hyphen.start and hyphen.end == last.start
    text = first.text + hyphen.text + last.text
    if not is_one_run or text not in COMPOUND_WORDS:
        return None
    return Token("word", text, first.start, last.end, first.accented or last.accented)


def _join_compounds(tokens: Sequence[Token]) -> list[Token]:
    """Only known compounds are joined, so "terça-sábado" stays two words around a hyphen."""
    joined: list[Token] = []
    index = 0
    while index < len(tokens):
        compound = _compound_at(tokens, index)
        joined.append(compound or tokens[index])
        index += 3 if compound else 1
    return joined


def tokenize(text: str) -> list[Token]:
    folded, offsets = _fold(text)
    tokens: list[Token] = []
    for match in _TOKEN.finditer(_blank_list_markers(folded)):
        kind = next(kind for kind in _KINDS if match.group(kind) is not None)
        start, end = offsets[match.start()], offsets[match.end()]
        accented = text[start:end].lower() != match.group()
        tokens.append(Token(kind, match.group(), start, end, accented))
    return _join_compounds(tokens)


def word_at(tokens: Sequence[Token], index: int) -> str | None:
    """The folded text of the token at `index` when it exists and is a word."""
    if 0 <= index < len(tokens) and tokens[index].kind == "word":
        return tokens[index].text
    return None


def symbol_at(tokens: Sequence[Token], index: int) -> str | None:
    if 0 <= index < len(tokens) and tokens[index].kind == "symbol":
        return tokens[index].text
    return None


def words_at(tokens: Sequence[Token], index: int, words: Sequence[str]) -> bool:
    return all(word_at(tokens, index + offset) == word for offset, word in enumerate(words))


def is_glued(tokens: Sequence[Token], index: int) -> bool:
    """Whether the token at `index` exists and touches the one before it."""
    return 0 < index < len(tokens) and tokens[index - 1].end == tokens[index].start
