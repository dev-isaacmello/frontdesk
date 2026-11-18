"""GRD-7: before anything else, what goes to a customer has to be a text.

The other checks read a reply for what it states. A reply that states nothing passes all
of them, and two such replies reached the first real conversation: one empty, which the
channel refused, and one of dots, line breaks and stray words, which it delivered.
"""

import unicodedata
from typing import Literal

_WORDY_SHARE = 0.5
"""Of the characters that show, how many have to be letters or digits. A price alone, a
list of times and a one-word answer are all above it; punctuation in a row is not."""


def not_a_text(draft: str) -> Literal["empty", "garbled"] | None:
    """Why a draft is not something to send, or None when it reads as a text."""
    # Format characters, such as a zero-width space, take no room and say nothing.
    shown = [
        character
        for character in draft
        if not character.isspace() and unicodedata.category(character) != "Cf"
    ]
    if not shown:
        return "empty"
    wordy = sum(1 for character in shown if character.isalnum())
    return "garbled" if wordy / len(shown) < _WORDY_SHARE else None
