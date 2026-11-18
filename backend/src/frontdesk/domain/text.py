"""Text that came from outside, made safe to store and to show.

PostgreSQL refuses a NUL byte in text and in jsonb, so one of them in a customer message,
in what an owner typed or in what a model wrote fails the write that carries it. The other
control characters are storable and mean nothing in a chat. Both are removed where text
enters: the inbound message, the request bodies of the panel, and every model response.
"""

import re
from typing import Annotated, Any

from pydantic import AfterValidator

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
"""The C0 control characters and DEL, except tab, line feed and carriage return."""


def storable(text: str) -> str:
    return _CONTROL.sub("", text)


def storable_json(value: Any) -> Any:
    """The same document with every string in it, keys included, made storable."""
    if isinstance(value, str):
        return storable(value)
    if isinstance(value, dict):
        return {storable_json(key): storable_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [storable_json(item) for item in value]
    return value


Storable = Annotated[str, AfterValidator(storable)]
"""A field of a request body that is stored as text."""
