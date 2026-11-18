"""Reading a reply one sentence at a time, and telling a statement from its negation."""

import re
from collections.abc import Iterator

_SENTENCE_END = re.compile(r"[.!?;\n]+")
_NEGATION = re.compile(r"\b(?:não|nao|nem|nenhum|nenhuma|sem|nunca|jamais)\b", re.IGNORECASE)


def affirmed(pattern: re.Pattern[str], text: str) -> Iterator[re.Match[str]]:
    """The matches of `pattern` that are not in a negated sentence.

    A sentence is negated when a negation word comes before the match: "não temos
    desconto" denies, "temos desconto, não é?" does not.
    """
    for sentence in _SENTENCE_END.split(text):
        for match in pattern.finditer(sentence):
            if not _NEGATION.search(sentence[: match.start()]):
                yield match
