"""The message that tells a worker a conversation has work waiting.

It carries ids and no content. The content is in PostgreSQL (ADR 0001).
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Trigger:
    tenant_id: UUID
    conversation_id: UUID
    traceparent: str | None = None
    """The trace the message arrived in, so that the worker's spans join it."""
