"""The inbox, the turns and the outbox of a conversation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.agent.turn import HistoryMessage, TurnInput, TurnResult
from frontdesk.channels.port import OutboundMessage
from frontdesk.db.models import ChannelAccount as ChannelAccountRow
from frontdesk.db.models import (
    Conversation,
    CustomerIdentity,
    Handoff,
    InboundEvent,
    Message,
    Turn,
)
from frontdesk.domain.customers import Channel, ChannelIdentity, identify_customer

_HISTORY_WINDOW = 20
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

    lines = await _lines(session, conversation_id)
    return TurnInput(
        tenant_id=conversation.tenant_id,
        customer_id=conversation.customer_id,
        turn_id=turn.id,
        now=turn.started_at,
        messages=[line.body for line in lines if line.turn_id == turn.id],
        history=[
            HistoryMessage(author=cast("Literal['customer', 'agent']", line.author), text=line.body)
            for line in lines
            if line.turn_id is not None and line.turn_id != turn.id
        ][-_HISTORY_WINDOW:],
    )


async def close_turn(
    session: AsyncSession, conversation_id: UUID, turn: TurnInput, result: TurnResult, now: datetime
) -> None:
    """Completes the turn and puts its reply in the outbox, as one change."""
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
            seq=0,
        )
        .on_conflict_do_nothing()
    )
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
