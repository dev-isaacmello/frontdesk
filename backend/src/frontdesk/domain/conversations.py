"""The inbox, the turns and the outbox of a conversation."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.agent.turn import HistoryMessage, TurnInput, TurnResult
from frontdesk.channels.port import OutboundMessage
from frontdesk.db.models import (
    ApprovalRequest,
    Conversation,
    CustomerIdentity,
    Handoff,
    InboundEvent,
    Message,
    Turn,
)
from frontdesk.db.models import ChannelAccount as ChannelAccountRow
from frontdesk.domain import approvals
from frontdesk.domain.customers import Channel, ChannelIdentity, identify_customer

_HISTORY_WINDOW = 20
_LEASE = timedelta(minutes=3)
"""How long a worker may hold a conversation without finishing. Past it, another worker
takes over, and the first one's final write is refused."""


class ConversationBusyError(Exception):
    """Another worker holds the conversation and its lease has not run out."""


class StaleLeaseError(Exception):
    """This worker's lease on the conversation was taken over, so its turn is not written."""


_RESOLVE_ACCOUNT = text(
    "select tenant_id, channel_account_id from resolve_channel_account(:channel, :external_id)"
)


@dataclass(frozen=True)
class ChannelAccount:
    tenant_id: UUID
    id: UUID
    channel: Channel


@dataclass(frozen=True)
class InboundMessage:
    """A customer message as any channel delivers it."""

    provider_message_id: str
    sender: ChannelIdentity
    text: str
    sent_at: datetime
    raw: dict[str, Any]


@dataclass(frozen=True)
class Receipt:
    conversation_id: UUID
    duplicate: bool
    pending: bool
    """Whether the message still waits for a turn, which is when a trigger is worth sending."""


@dataclass(frozen=True)
class Reply:
    message_id: UUID
    text: str


@dataclass(frozen=True)
class TranscriptLine:
    author: str
    text: str
    occurred_at: datetime


async def find_channel_account(
    session: AsyncSession, channel: Channel, external_id: str
) -> ChannelAccount | None:
    """Finds the tenant behind a channel address. Works before any tenant is set."""
    row = (
        await session.execute(_RESOLVE_ACCOUNT, {"channel": channel, "external_id": external_id})
    ).one_or_none()
    return None if row is None else ChannelAccount(row.tenant_id, row.channel_account_id, channel)


async def receive(
    session: AsyncSession, account: ChannelAccount, message: InboundMessage
) -> Receipt:
    """Stores an inbound message once, however many times the provider delivers it."""
    event_id = await session.scalar(
        insert(InboundEvent)
        .values(
            tenant_id=account.tenant_id,
            channel_account_id=account.id,
            provider_message_id=message.provider_message_id,
            raw=message.raw,
        )
        .on_conflict_do_nothing()
        .returning(InboundEvent.id)
    )
    if event_id is None:
        return await _receipt_of_redelivery(session, account, message)

    customer_id = await identify_customer(session, account.tenant_id, message.sender)
    conversation_id = await session.scalar(
        insert(Conversation)
        .values(
            tenant_id=account.tenant_id,
            channel_account_id=account.id,
            customer_id=customer_id,
            last_inbound_at=message.sent_at,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "channel_account_id", "customer_id"],
            set_={"last_inbound_at": message.sent_at},
        )
        .returning(Conversation.id)
    )
    assert conversation_id is not None
    session.add(
        Message(
            tenant_id=account.tenant_id,
            conversation_id=conversation_id,
            direction="in",
            author="customer",
            body=message.text,
            occurred_at=message.sent_at,
            inbound_event_id=event_id,
        )
    )
    return Receipt(conversation_id, duplicate=False, pending=True)


async def open_turn(
    session: AsyncSession, conversation_id: UUID, now: datetime
) -> TurnInput | None:
    """Starts a turn over the waiting messages, or resumes the one that did not finish.

    Returns None when there is nothing to do, which is the normal answer to a trigger
    that arrives after its message was already handled.
    """
    conversation = await session.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    if conversation is None:
        return None

    turn = await session.scalar(
        select(Turn).where(Turn.conversation_id == conversation_id, Turn.status == "running")
    )
    if turn is not None and conversation.lease_until is not None and conversation.lease_until > now:
        # The queue gives a conversation to one worker at a time, but its lock can be lost
        # while the first worker is still running. This is the lock that holds then.
        raise ConversationBusyError
    if turn is None:
        waiting = select(Message.id).where(
            Message.conversation_id == conversation_id,
            Message.direction == "in",
            Message.turn_id.is_(None),
        )
        if (await session.scalars(waiting.limit(1))).first() is None:
            return None
        in_handoff = conversation.mode == "handoff"
        turn = Turn(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation_id,
            started_at=now,
            # With a person in charge the agent stays silent. The messages are still
            # taken, so that they stop waking the worker, and the panel shows them.
            status="completed" if in_handoff else "running",
            outcome="silent" if in_handoff else None,
            finished_at=now if in_handoff else None,
        )
        session.add(turn)
        await session.flush()
        await session.execute(
            update(Message).where(Message.id.in_(waiting)).values(turn_id=turn.id)
        )
        if in_handoff:
            return None

    return await _take(session, conversation, turn, now)


async def reopen_turn(
    session: AsyncSession, conversation_id: UUID, turn_id: UUID, now: datetime
) -> TurnInput | None:
    """Takes up a turn that stopped for approval, under a new lease. None if it is gone."""
    conversation = await session.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    turn = await session.scalar(
        select(Turn).where(Turn.id == turn_id, Turn.status == "awaiting_approval")
    )
    if conversation is None or turn is None:
        return None
    return await _take(session, conversation, turn, now)


async def _take(
    session: AsyncSession, conversation: Conversation, turn: Turn, now: datetime
) -> TurnInput:
    """Leases the conversation to the caller and describes the turn it is to run."""
    conversation.lease_epoch += 1
    conversation.lease_until = now + _LEASE
    lines = await _lines(session, conversation.id)
    return TurnInput(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        customer_id=conversation.customer_id,
        turn_id=turn.id,
        lease_epoch=conversation.lease_epoch,
        now=turn.started_at,
        messages=[
            line.body for line in lines if line.turn_id == turn.id and line.direction == "in"
        ],
        history=[
            HistoryMessage(author=cast("Literal['customer', 'agent']", line.author), text=line.body)
            for line in lines
            if line.turn_id is not None and line.turn_id != turn.id
        ][-_HISTORY_WINDOW:],
    )


async def close_turn(
    session: AsyncSession, conversation_id: UUID, turn: TurnInput, result: TurnResult, now: datetime
) -> None:
    """Ends this run of the turn and puts what it says in the outbox, as one change.

    A turn that stops for approval is not finished: its wait notice goes out, the request
    is recorded, and the turn stays open for the owner's decision.
    Refused with StaleLeaseError when another worker took the conversation over meanwhile.
    """
    if not await release_lease(session, conversation_id, turn.lease_epoch):
        raise StaleLeaseError
    already_said = await session.scalar(
        select(func.count()).where(Message.turn_id == turn.turn_id, Message.direction == "out")
    )
    await session.execute(
        insert(Message)
        .values(
            tenant_id=turn.tenant_id,
            conversation_id=conversation_id,
            direction="out",
            author="agent",
            body=result.reply,
            occurred_at=now,
            turn_id=turn.turn_id,
            # The reply of a resumed turn comes after the wait notice it already sent.
            seq=already_said or 0,
        )
        .on_conflict_do_nothing()
    )
    if result.outcome == "awaiting_approval":
        assert result.approval is not None
        await session.execute(
            update(Turn)
            .where(Turn.id == turn.turn_id)
            .values(status="awaiting_approval", outcome="awaiting_approval")
        )
        await approvals.request(
            session, turn.tenant_id, conversation_id, turn.turn_id, result.approval, now
        )
        return
    await session.execute(
        update(Turn)
        .where(Turn.id == turn.turn_id)
        .values(status="completed", outcome=result.outcome, finished_at=now)
    )
    if result.outcome == "handoff":
        await session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(mode="handoff")
        )
        session.add(
            Handoff(
                tenant_id=turn.tenant_id,
                conversation_id=conversation_id,
                turn_id=turn.turn_id,
                reason=result.handoff_reason,
                opened_at=now,
            )
        )


async def release_lease(session: AsyncSession, conversation_id: UUID, epoch: int) -> bool:
    """Lets the conversation go if this epoch still holds it. Returns whether it did."""
    held = await session.scalar(
        update(Conversation)
        .where(Conversation.id == conversation_id, Conversation.lease_epoch == epoch)
        .values(lease_until=None)
        .returning(Conversation.id)
    )
    return held is not None


async def newest_waiting(session: AsyncSession, conversation_id: UUID) -> datetime | None:
    """When the latest customer message still waiting for a turn was sent."""
    newest: datetime | None = await session.scalar(
        select(func.max(Message.occurred_at)).where(
            Message.conversation_id == conversation_id,
            Message.direction == "in",
            Message.turn_id.is_(None),
        )
    )
    return newest


async def give_up(session: AsyncSession, conversation_id: UUID, notice: str, now: datetime) -> None:
    """Ends the attempt to answer: the conversation goes to a person and the customer is told.

    Called when a turn failed through all its retries. Does nothing when a person is
    already in charge, so calling it again is safe.
    """
    conversation = await session.scalar(
        select(Conversation).where(Conversation.id == conversation_id).with_for_update()
    )
    if conversation is None or conversation.mode == "handoff":
        return
    turn = await session.scalar(
        select(Turn).where(Turn.conversation_id == conversation_id, Turn.status == "running")
    )
    if turn is not None:
        turn.status, turn.outcome, turn.finished_at = "failed", "failed", now
    # A paused turn whose decision could not be acted on is closed as well, so that the
    # decision stops waking the worker.
    await session.execute(
        update(Turn)
        .where(
            Turn.conversation_id == conversation_id,
            Turn.status == "awaiting_approval",
            Turn.id.in_(
                select(ApprovalRequest.turn_id).where(
                    ApprovalRequest.conversation_id == conversation_id,
                    ApprovalRequest.status != "pending",
                    ApprovalRequest.resumed_at.is_(None),
                )
            ),
        )
        .values(status="failed", outcome="failed", finished_at=now)
    )
    session.add(
        Message(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation_id,
            direction="out",
            author="agent",
            body=notice,
            occurred_at=now,
            turn_id=turn.id if turn else None,
            seq=0 if turn else None,
        )
    )
    conversation.mode = "handoff"
    conversation.lease_until = None
    session.add(
        Handoff(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation_id,
            turn_id=turn.id if turn else None,
            reason="agent_failed",
            opened_at=now,
        )
    )


async def undelivered(session: AsyncSession, conversation_id: UUID) -> list[OutboundMessage]:
    rows = await session.execute(
        select(Message, ChannelAccountRow.channel, CustomerIdentity.external_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .join(ChannelAccountRow, ChannelAccountRow.id == Conversation.channel_account_id)
        .join(
            CustomerIdentity,
            (CustomerIdentity.customer_id == Conversation.customer_id)
            & (CustomerIdentity.channel == ChannelAccountRow.channel),
        )
        .where(
            Message.conversation_id == conversation_id,
            Message.direction == "out",
            Message.sent_at.is_(None),
        )
        .order_by(Message.occurred_at, Message.id)
    )
    return [
        OutboundMessage(
            message_id=message.id,
            tenant_id=message.tenant_id,
            conversation_id=message.conversation_id,
            channel=cast("Channel", channel),
            recipient_external_id=external_id,
            text=message.body,
        )
        for message, channel, external_id in rows
    ]


async def mark_sent(
    session: AsyncSession, message_id: UUID, provider_message_id: str | None, now: datetime
) -> None:
    await session.execute(
        update(Message)
        .where(Message.id == message_id)
        .values(sent_at=now, provider_message_id=provider_message_id)
    )


async def belongs_to(
    session: AsyncSession, conversation_id: UUID, account: ChannelAccount, sender_external_id: str
) -> bool:
    """Whether a conversation is the one that customer has on that channel account."""
    found = await session.scalar(
        select(Conversation.id)
        .join(
            CustomerIdentity,
            (CustomerIdentity.customer_id == Conversation.customer_id)
            & (CustomerIdentity.channel == account.channel),
        )
        .where(
            Conversation.id == conversation_id,
            Conversation.channel_account_id == account.id,
            CustomerIdentity.external_id == sender_external_id,
        )
    )
    return found is not None


async def replies_after(
    session: AsyncSession, conversation_id: UUID, cursor: UUID | None
) -> list[Reply]:
    """The agent's replies written after the one the cursor names, oldest first."""
    query = (
        select(Message.id, Message.body)
        .where(Message.conversation_id == conversation_id, Message.direction == "out")
        .order_by(Message.id)
    )
    if cursor is not None:
        query = query.where(Message.id > cursor)
    return [Reply(message_id, body) for message_id, body in await session.execute(query)]


async def transcript(session: AsyncSession, conversation_id: UUID) -> list[TranscriptLine]:
    return [
        TranscriptLine(author=line.author, text=line.body, occurred_at=line.occurred_at)
        for line in await _lines(session, conversation_id)
    ]


async def _receipt_of_redelivery(
    session: AsyncSession, account: ChannelAccount, message: InboundMessage
) -> Receipt:
    row = (
        await session.execute(
            select(Message.conversation_id, Message.turn_id)
            .join(InboundEvent, InboundEvent.id == Message.inbound_event_id)
            .where(
                InboundEvent.channel_account_id == account.id,
                InboundEvent.provider_message_id == message.provider_message_id,
            )
        )
    ).one()
    return Receipt(row.conversation_id, duplicate=True, pending=row.turn_id is None)


async def _lines(session: AsyncSession, conversation_id: UUID) -> list[Message]:
    return list(
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.occurred_at, Message.created_at, Message.id)
        )
    )
