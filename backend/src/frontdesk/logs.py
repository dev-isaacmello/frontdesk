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


class _NoQueryString(logging.Filter):
    """Cuts the query string from the request line the HTTP server logs.

    Meta checks a webhook by sending its verify token in the query string, and the server's
    access log writes the whole target: on the first deployment the token was in the log.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn logs a request as (client, method, target, HTTP version, status).
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, target, version, status = record.args
            record.args = (client, method, str(target).split("?", 1)[0], version, status)
        return True


_ACCESS_LOG = "uvicorn.access"


def configure(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
    access = logging.getLogger(_ACCESS_LOG)
    if not any(isinstance(existing, _NoQueryString) for existing in access.filters):
        access.addFilter(_NoQueryString())
    # The Azure SDKs log every AMQP frame and HTTP request at INFO.
    logging.getLogger("azure").setLevel(logging.WARNING)


def failure(error: BaseException) -> dict[str, str]:
    """Fields that describe an error without repeating the data it carried."""
    return {
        "error_type": type(error).__qualname__,
        "error_trace": "".join(traceback.format_tb(error.__traceback__)),
    }
