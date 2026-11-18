"""What the owner's panel reads. The tenant is always the one of the session."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from frontdesk.db.models import (
    ApprovalRequest,
    Booking,
    Conversation,
    Customer,
    Handoff,
    Message,
    ModelCall,
    Resource,
    Service,
    Turn,
    TurnStep,
)

_PREVIEW = 90


@dataclass(frozen=True)
class ConversationSummary:
    id: UUID
    customer_name: str | None
    mode: str
    last_message_at: datetime
    last_message_preview: str
    last_author: str
    pending_approval: bool


@dataclass(frozen=True)
class Line:
    id: UUID
    author: str
    text: str
    at: datetime


@dataclass(frozen=True)
class StepLine:
    seq: int
    node: str
    duration_ms: int
    detail: dict[str, Any]


@dataclass(frozen=True)
class TurnLine:
    id: UUID
    status: str
    outcome: str | None
    started_at: datetime
    finished_at: datetime | None
    blocked_drafts: int
    model_calls: int
    cost_microusd: int
    steps: list[StepLine]


@dataclass(frozen=True)
class ConversationDetail:
    id: UUID
    customer_name: str | None
    mode: str
    messages: list[Line]
    turns: list[TurnLine]


@dataclass(frozen=True)
class WaitingApproval:
    id: UUID
    conversation_id: UUID
    customer_name: str | None
    rule: str
    tool: str
    requested_at: datetime
    service_name: str | None
    resource_name: str | None
    starts_at: datetime | None
    """The booking the request is about, when it still exists."""


async def conversations(session: AsyncSession) -> list[ConversationSummary]:
    """Every conversation of the tenant, the one with the latest message first."""
    # The newest message of each conversation. Ids are UUIDv7, so they sort by time.
    newest = aliased(
        Message,
        select(Message)
        .ext(distinct_on(Message.conversation_id))
        .order_by(Message.conversation_id, Message.id.desc())
        .subquery(),
    )
    pending = (
        select(ApprovalRequest.conversation_id)
        .where(ApprovalRequest.status == "pending")
        .subquery()
    )
    rows = await session.execute(
        select(Conversation, Customer.display_name, newest, pending.c.conversation_id)
        .join(Customer, Customer.id == Conversation.customer_id)
        .join(newest, newest.conversation_id == Conversation.id)
        .outerjoin(pending, pending.c.conversation_id == Conversation.id)
        .order_by(newest.id.desc())
    )
    return [
        ConversationSummary(
            id=conversation.id,
            customer_name=name,
            mode=conversation.mode,
            last_message_at=message.occurred_at,
            last_message_preview=message.body[:_PREVIEW],
            last_author=message.author,
            pending_approval=waiting is not None,
        )
        for conversation, name, message, waiting in rows
    ]


async def conversation(session: AsyncSession, conversation_id: UUID) -> ConversationDetail | None:
    found = (
        await session.execute(
            select(Conversation, Customer.display_name)
            .join(Customer, Customer.id == Conversation.customer_id)
            .where(Conversation.id == conversation_id)
        )
    ).one_or_none()
    if found is None:
        return None
    row, name = found
    messages = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.occurred_at, Message.created_at, Message.id)
    )
    return ConversationDetail(
        id=row.id,
        customer_name=name,
        mode=row.mode,
        messages=[Line(m.id, m.author, m.body, m.occurred_at) for m in messages],
        turns=await _turns(session, conversation_id),
    )


async def _turns(session: AsyncSession, conversation_id: UUID) -> list[TurnLine]:
    turns = list(
        await session.scalars(
            select(Turn).where(Turn.conversation_id == conversation_id).order_by(Turn.id)
        )
    )
    ids = [turn.id for turn in turns]
    steps: dict[UUID, list[StepLine]] = {turn_id: [] for turn_id in ids}
    for step in await session.scalars(
        select(TurnStep).where(TurnStep.turn_id.in_(ids)).order_by(TurnStep.turn_id, TurnStep.seq)
    ):
        steps[step.turn_id].append(StepLine(step.seq, step.node, step.duration_ms, step.detail))
    spent = {
        turn_id: (calls, cost)
        for turn_id, calls, cost in await session.execute(
            select(ModelCall.turn_id, func.count(), func.sum(ModelCall.cost_microusd))
            .where(ModelCall.turn_id.in_(ids))
            .group_by(ModelCall.turn_id)
        )
    }
    return [
        TurnLine(
            id=turn.id,
            status=turn.status,
            outcome=turn.outcome,
            started_at=turn.started_at,
            finished_at=turn.finished_at,
            blocked_drafts=turn.blocked_drafts,
            model_calls=spent.get(turn.id, (0, 0))[0],
            cost_microusd=int(spent.get(turn.id, (0, 0))[1]),
            steps=steps[turn.id],
        )
        for turn in turns
    ]


async def waiting_approvals(session: AsyncSession) -> list[WaitingApproval]:
    """The requests waiting for the owner, oldest first, with the booking each is about."""
    rows = await session.execute(
        select(ApprovalRequest, Customer.display_name)
        .join(Conversation, Conversation.id == ApprovalRequest.conversation_id)
        .join(Customer, Customer.id == Conversation.customer_id)
        .where(ApprovalRequest.status == "pending")
        .order_by(ApprovalRequest.requested_at)
    )
    waiting = []
    for request, name in rows:
        booking = await _booking_of(session, request.arguments.get("booking_id"))
        waiting.append(
            WaitingApproval(
                id=request.id,
                conversation_id=request.conversation_id,
                customer_name=name,
                rule=request.rule,
                tool=request.tool,
                requested_at=request.requested_at,
                service_name=booking[0] if booking else None,
                resource_name=booking[1] if booking else None,
                starts_at=booking[2] if booking else None,
            )
        )
    return waiting


async def _booking_of(
    session: AsyncSession, booking_id: object
) -> tuple[str, str, datetime | None] | None:
    try:
        wanted = UUID(str(booking_id))
    except ValueError:
        return None
    row = (
        await session.execute(
            select(Service.name, Resource.name, Booking.during)
            .join(Service, Service.id == Booking.service_id)
            .join(Resource, Resource.id == Booking.resource_id)
            .where(Booking.id == wanted)
        )
    ).one_or_none()
    return None if row is None else (row[0], row[1], row[2].lower)


async def say_as_owner(
    session: AsyncSession, conversation_id: UUID, text: str, now: datetime
) -> bool:
    """Writes the owner's message to the outbox. Only while a person is in charge."""
    row = await session.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    if row is None or row.mode != "handoff":
        return False
    session.add(
        Message(
            tenant_id=row.tenant_id,
            conversation_id=conversation_id,
            direction="out",
            author="owner",
            body=text,
            occurred_at=now,
        )
    )
    return True


async def return_to_agent(session: AsyncSession, conversation_id: UUID, now: datetime) -> bool:
    """Ends the handoff. The agent answers the next message again."""
    returned = await session.scalar(
        update(Conversation)
        .where(Conversation.id == conversation_id, Conversation.mode == "handoff")
        .values(mode="agent")
        .returning(Conversation.id)
    )
    if returned is None:
        return False
    await session.execute(
        update(Handoff)
        .where(Handoff.conversation_id == conversation_id, Handoff.resolved_at.is_(None))
        .values(resolved_at=now)
    )
    return True
