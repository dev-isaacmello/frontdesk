"""What goes into a turn and what comes out of it."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID


@dataclass(frozen=True)
class HistoryMessage:
    author: Literal["customer", "agent"]
    text: str


@dataclass(frozen=True)
class TurnInput:
    tenant_id: UUID
    customer_id: UUID
    turn_id: UUID
    now: datetime
    messages: list[str]
    history: list[HistoryMessage]


type HandoffReason = Literal[
    "customer_asked", "agent_failed", "guardrail_blocked", "turn_limit", "budget_exhausted"
]


@dataclass(frozen=True)
class TurnResult:
    outcome: Literal["replied", "refused", "handoff"]
    reply: str
    handoff_reason: HandoffReason | None = None
    """Why the conversation goes to a person. Set when the outcome is handoff."""
