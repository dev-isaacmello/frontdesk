"""The WhatsApp Cloud API: what a webhook carries and how a reply is sent (ING-8).

The shapes and limits used here were read in Meta's documentation and are recorded with
their sources in docs/verificado.md.
"""

import hashlib
import hmac
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import SecretStr
from sqlalchemy import func, select

from frontdesk.channels.port import (
    ChannelCost,
    ChannelRejectedError,
    ChannelUnavailableError,
    OutboundMessage,
    SendReceipt,
)
from frontdesk.db.models import Message
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.conversations import InboundMessage
from frontdesk.domain.customers import ChannelIdentity

GRAPH_URL = "https://graph.facebook.com/v27.0"

SEND_INTERVAL = timedelta(seconds=6)
"""Meta accepts one message every six seconds to the same user, and answers the next one
sooner with error 131056."""

SERVICE_MESSAGE = ChannelCost(micros=35_000, currency="BRL")
"""A delivered service message to a Brazilian number past the monthly free tier, on the
rate card in force since 2026-10-01."""

_WAIT_AND_RETRY = frozenset({4, 80007, 130429, 131056})
"""Throttling codes, which Meta documents as worth sending again after a wait."""

_SIGNATURE_PREFIX = "sha256="

log = logging.getLogger(__name__)


def signed_by_meta(app_secret: str, body: bytes, signature: str | None) -> bool:
    """Whether the header is the HMAC-SHA256 of these exact bytes under the app secret."""
    if not signature or not signature.startswith(_SIGNATURE_PREFIX):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix(_SIGNATURE_PREFIX))


@dataclass(frozen=True)
class Received:
    phone_number_id: str
    """The business number the message was sent to, which is what a tenant is found by."""
    message: InboundMessage


@dataclass(frozen=True)
class Delivery:
    """What Meta says later about a message that was sent."""

    phone_number_id: str
    provider_message_id: str
    status: str
    cost: ChannelCost | None
    """What the message is charged, when the update says. None when it does not."""


@dataclass(frozen=True)
class Webhook:
    messages: list[Received]
    deliveries: list[Delivery]
    ignored: int
    """Messages that are not text, or that lack what a message needs to be answered."""


def parse(payload: Any) -> Webhook:
    """Reads one webhook request. It is input from outside: nothing in it is assumed."""
    messages: list[Received] = []
    deliveries: list[Delivery] = []
    ignored = 0
    for value in _values(payload):
        phone_number_id = _text(_dict(value.get("metadata")).get("phone_number_id"))
        if phone_number_id is None:
            continue
        names = _names(value.get("contacts"))
        for raw in _dicts(value.get("messages")):
            message = _message(raw, names)
            if message is None:
                ignored += 1
            else:
                messages.append(Received(phone_number_id, message))
        for raw in _dicts(value.get("statuses")):
            delivery = _delivery(phone_number_id, raw)
            if delivery is not None:
                deliveries.append(delivery)
    return Webhook(messages, deliveries, ignored)


def _message(raw: dict[str, Any], names: dict[str, str]) -> InboundMessage | None:
    message_id = _text(raw.get("id"))
    phone = _text(raw.get("from"))
    # Meta's own advice is to know a customer by the business-scoped user id: the phone
    # is left out once the customer has a username.
    user_id = _text(raw.get("from_user_id")) or phone
    body = _text(_dict(raw.get("text")).get("body"))
    sent_at = _instant(raw.get("timestamp"))
    if raw.get("type") != "text" or not (message_id and user_id and body and sent_at):
        return None
    return InboundMessage(
        provider_message_id=message_id,
        sender=ChannelIdentity(
            channel="whatsapp",
            external_id=user_id,
            display_name=names.get(user_id) or (names.get(phone) if phone else None),
            phone=phone,
        ),
        text=body,
        sent_at=sent_at,
        raw=raw,
    )


def _delivery(phone_number_id: str, raw: dict[str, Any]) -> Delivery | None:
    message_id, status = _text(raw.get("id")), _text(raw.get("status"))
    if not (message_id and status):
        return None
    pricing = _dict(raw.get("pricing"))
    cost: ChannelCost | None = None
    if pricing.get("billable") is False:
        cost = ChannelCost(micros=0, currency=SERVICE_MESSAGE.currency)
    elif pricing.get("billable") is True and pricing.get("category") == "service":
        cost = SERVICE_MESSAGE
    return Delivery(phone_number_id, message_id, status, cost)


def _names(contacts: Any) -> dict[str, str]:
    """The profile name of each contact, under every identifier the payload gives it."""
    names: dict[str, str] = {}
    for contact in _dicts(contacts):
        name = _text(_dict(contact.get("profile")).get("name"))
        for key in ("user_id", "wa_id"):
            identifier = _text(contact.get(key))
            if name and identifier:
                names[identifier] = name
    return names


def _values(payload: Any) -> list[dict[str, Any]]:
    return [
        _dict(change.get("value"))
        for entry in _dicts(_dict(payload).get("entry"))
        for change in _dicts(entry.get("changes"))
    ]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _instant(value: Any) -> datetime | None:
    """A Unix time in seconds, which Meta sends as a string."""
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


class WhatsAppSender:
    """Sends a text through the Graph API, no sooner than Meta accepts for one customer."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        sessions: SessionFactory,
        access_token: SecretStr,
        *,
        clock: Callable[[], datetime],
        sleep: Callable[[float], Awaitable[None]],
        timeout_s: float = 10,
    ) -> None:
        self._client = client
        self._sessions = sessions
        self._token = access_token
        self._clock = clock
        self._sleep = sleep
        self._timeout_s = timeout_s

    async def send(self, message: OutboundMessage) -> SendReceipt:
        await self._wait_for_the_interval(message)
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "type": "text",
            "text": {"preview_url": False, "body": message.text},
        }
        if message.recipient_phone:
            body["to"] = message.recipient_phone
        else:
            body["recipient"] = message.recipient_external_id
        try:
            response = await self._client.post(
                f"{GRAPH_URL}/{message.account_external_id}/messages",
                json=body,
                headers={"Authorization": f"Bearer {self._token.get_secret_value()}"},
                timeout=self._timeout_s,
            )
        except httpx.HTTPError as error:
            raise ChannelUnavailableError(type(error).__name__) from error
        if response.is_success:
            # What it cost is not known yet: Meta charges on delivery and says so later.
            return SendReceipt(provider_message_id=_sent_id(response), cost=None)
        raise _failure(response)

    async def _wait_for_the_interval(self, message: OutboundMessage) -> None:
        async with tenant_transaction(self._sessions, message.tenant_id) as session:
            last = await session.scalar(
                select(func.max(Message.sent_at)).where(
                    Message.conversation_id == message.conversation_id,
                    Message.direction == "out",
                )
            )
        if last is None:
            return
        remaining = SEND_INTERVAL - (self._clock() - last)
        if remaining > timedelta(0):
            await self._sleep(remaining.total_seconds())


def _sent_id(response: httpx.Response) -> str | None:
    try:
        sent = _dicts(_dict(response.json()).get("messages"))
    except ValueError:
        return None
    return _text(sent[0].get("id")) if sent else None


def _failure(response: httpx.Response) -> Exception:
    try:
        error = _dict(_dict(response.json()).get("error"))
    except ValueError:
        error = {}
    code = error.get("code")
    reason = f"{response.status_code}/{code}"
    if response.status_code >= 500 or code in _WAIT_AND_RETRY:
        return ChannelUnavailableError(reason)
    return ChannelRejectedError(reason)
