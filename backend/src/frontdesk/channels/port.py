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


@dataclass(frozen=True)
class SendReceipt:
    provider_message_id: str | None


class ChannelSender(Protocol):
    async def send(self, message: OutboundMessage) -> SendReceipt: ...
