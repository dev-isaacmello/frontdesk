"""Request signing between the panel's server and the API.

The signature covers a timestamp, the method, the path and the exact bytes of the body,
so a request cannot be altered or replayed later. It is checked before the body is parsed.
"""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

TIMESTAMP_HEADER = "X-Frontdesk-Timestamp"
SIGNATURE_HEADER = "X-Frontdesk-Signature"

_MAX_AGE = timedelta(minutes=5)
_SCHEME = "sha256="


def sign(secret: str, at: datetime, method: str, path: str, body: bytes) -> tuple[str, str]:
    """Returns the values of the timestamp header and the signature header."""
    timestamp = str(int(at.timestamp()))
    return timestamp, _SCHEME + _digest(secret, timestamp, method, path, body)


def verify(
    secret: str,
    now: datetime,
    method: str,
    path: str,
    body: bytes,
    *,
    timestamp: str | None,
    signature: str | None,
) -> bool:
    if timestamp is None or signature is None or not timestamp.isdecimal():
        return False
    signed_at = datetime.fromtimestamp(int(timestamp), UTC)
    if abs(now - signed_at) > _MAX_AGE:
        return False
    expected = _SCHEME + _digest(secret, timestamp, method, path, body)
    return hmac.compare_digest(expected, signature)


def _digest(secret: str, timestamp: str, method: str, path: str, body: bytes) -> str:
    signed = f"{timestamp}.{method.upper()}.{path}.".encode() + body
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
