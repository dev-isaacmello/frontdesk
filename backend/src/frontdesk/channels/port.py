"""The outbound half of a channel (docs/design/ports.md)."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from frontdesk.domain.customers import Channel


@dataclass(frozen=True)
class OutboundMessage:
    message_id: UUID
    tenant_id: UUID
    conversation_id: UUID
    channel: Channel
    recipient_external_id: str
    text: str
    account_external_id: str = ""
    """The tenant's own address on the channel: the WhatsApp phone number id it sends from."""
    recipient_phone: str | None = None


@dataclass(frozen=True)
class ChannelCost:
    """What a channel charged for one message, in millionths of the currency it charges in."""

    micros: int = 0
    currency: str = "USD"


@dataclass(frozen=True)
class SendReceipt:
    provider_message_id: str | None
    cost: ChannelCost | None = ChannelCost()
    """The web chat costs nothing. None when the channel only says later what it charged."""


class ChannelUnavailableError(Exception):
    """The channel could not take the message now. Sending it again later may work."""


class ChannelRejectedError(Exception):
    """The channel refused the message, and sending the same thing again will not help."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ChannelSender(Protocol):
    async def send(self, message: OutboundMessage) -> SendReceipt: ...
