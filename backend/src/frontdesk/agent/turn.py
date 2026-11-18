"""What goes into a turn and what comes out of it."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from frontdesk.domain.approvals import PendingApproval


@dataclass(frozen=True)
class HistoryMessage:
    author: Literal["customer", "agent"]
    text: str


@dataclass(frozen=True)
class TurnInput:
    tenant_id: UUID
    conversation_id: UUID
    customer_id: UUID
    turn_id: UUID
    now: datetime
    messages: list[str]
    history: list[HistoryMessage]
    lease_epoch: int = 0
    """The lease on the conversation this turn runs under. Its final write names it."""


type HandoffReason = Literal[
    "customer_asked", "agent_failed", "guardrail_blocked", "turn_limit", "budget_exhausted"
]


@dataclass(frozen=True)
class TurnResult:
    outcome: Literal["replied", "refused", "handoff", "awaiting_approval"]
    reply: str
    """What the customer is told. For a turn that waits for approval, the wait notice."""
    handoff_reason: HandoffReason | None = None
    """Why the conversation goes to a person. Set when the outcome is handoff."""

    approval: PendingApproval | None = None
    """The tool call that waits for the owner. Set when the outcome is awaiting_approval."""

    blocks: int = 0
    """How many drafts of the reply the checks refused before this result."""
