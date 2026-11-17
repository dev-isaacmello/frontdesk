"""Structured logs that carry ids and never what a customer wrote or is called.

Exception messages are not logged. Validation and driver errors quote the values they
failed on, which here means message bodies and names. The type of the error and the
frames it passed through are enough to find the cause.
"""

import json
import logging
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "at": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        entry.update({key: value for key, value in record.__dict__.items() if key not in _RESERVED})
        return json.dumps(entry, default=str)


def configure(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # The Azure SDKs log every AMQP frame and HTTP request at INFO.
    logging.getLogger("azure").setLevel(logging.WARNING)


def failure(error: BaseException) -> dict[str, str]:
    """Fields that describe an error without repeating the data it carried."""
    return {
        "error_type": type(error).__qualname__,
        "error_trace": "".join(traceback.format_tb(error.__traceback__)),
    }
