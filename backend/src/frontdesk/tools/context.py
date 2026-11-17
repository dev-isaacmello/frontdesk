"""What a tool knows about who is calling it.

The worker builds the context. Nothing in it comes from model output, so a tool cannot
be talked into acting for another tenant or another customer.
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class ToolContext:
    tenant_id: UUID
    customer_id: UUID
    now: datetime
    idempotency_key: str
