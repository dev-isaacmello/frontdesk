"""Helpers shared by tests that need a conversation to exist."""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text

from frontdesk.agent.graph import AgentDeps
from frontdesk.agent.turn import TurnInput
from frontdesk.channels.port import OutboundMessage, SendReceipt
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.conversations import (
    ChannelAccount,
    InboundMessage,
    Receipt,
    find_channel_account,
    open_turn,
    receive,
)
from frontdesk.domain.customers import ChannelIdentity
from frontdesk.providers.ledger import ModelLedger, ModelPrice, PriceTable
from frontdesk.providers.port import ModelResponse
from frontdesk.providers.scripted import ScriptedProvider, says
from frontdesk.seed import BARBERSHOP, TenantSeed
from frontdesk.worker.handler import WorkerDeps
from tests.tools.conftest import NOW

# USD 1.00 per million input tokens and 2.00 per million output tokens, so that the
# scripted model's 100 and 20 tokens cost 140 micro-USD per call.
PRICES = PriceTable(
    version="test",
    models={"scripted": ModelPrice(input=Decimal("1.00"), output=Decimal("2.00"))},
)


@dataclass
class RecordingSender:
    """Stands in for the channel provider, which is the external edge of the worker."""

    failing: bool = False
    sent: list[OutboundMessage] = field(default_factory=list)
    _arrived: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def send(self, message: OutboundMessage) -> SendReceipt:
        if self.failing:
            raise ConnectionError("channel is down")
        async with self._arrived:
            self.sent.append(message)
            self._arrived.notify_all()
        return SendReceipt(provider_message_id=f"out-{len(self.sent)}")

    async def has_sent(self, count: int) -> None:
        """Returns once at least `count` messages went out."""
        async with self._arrived:
            await self._arrived.wait_for(lambda: len(self.sent) >= count)


async def webchat_account(sessions: SessionFactory, tenant: TenantSeed) -> ChannelAccount:
    async with sessions() as session:
        account = await find_channel_account(session, "webchat", tenant.slug)
    assert account is not None
    return account


async def say(
    sessions: SessionFactory,
    text: str,
    message_id: str,
    *,
    sender: str = "Ana",
    tenant: TenantSeed = BARBERSHOP,
    sent_at: datetime = datetime(2026, 11, 18, 10, 0, tzinfo=UTC),
) -> Receipt:
    """A customer message arriving through the web chat of a tenant."""
    account = await webchat_account(sessions, tenant)
    message = InboundMessage(
        provider_message_id=message_id,
        sender=ChannelIdentity(channel="webchat", external_id=sender, display_name=sender),
        text=text,
        sent_at=sent_at,
        raw={"text": text},
    )
    async with tenant_transaction(sessions, account.tenant_id) as session:
        return await receive(session, account, message)


async def start_turn(
    sessions: SessionFactory, text: str, *, sender: str = "Ana", tenant: TenantSeed = BARBERSHOP
) -> TurnInput:
    """The turn a worker would open for a customer who just wrote `text`."""
    receipt = await say(sessions, text, f"{sender}:{text}", sender=sender, tenant=tenant)
    async with tenant_transaction(sessions, tenant.id) as session:
        turn = await open_turn(session, receipt.conversation_id, NOW)
    assert turn is not None
    return turn


IN_SCOPE = says('{"in_scope": true, "wants_human": false}')
OUT_OF_SCOPE = says('{"in_scope": false, "wants_human": false}')
WANTS_HUMAN = says('{"in_scope": true, "wants_human": true}')


def scripted_worker(
    sessions: SessionFactory, sender: RecordingSender, *script: ModelResponse
) -> tuple[WorkerDeps, ScriptedProvider]:
    """A worker whose model answers from a script, and the script to inspect afterwards."""
    provider = ScriptedProvider(script)
    deps = WorkerDeps(
        sessions=sessions,
        agent=AgentDeps(
            sessions=sessions,
            provider=provider,
            model="scripted",
            ledger=ModelLedger(sessions, PRICES),
        ),
        senders={"webchat": sender},
        clock=lambda: NOW,
    )
    return deps, provider


async def conversation_row(
    sessions: SessionFactory, conversation_id: UUID, tenant: TenantSeed = BARBERSHOP
) -> dict[str, Any]:
    async with tenant_transaction(sessions, tenant.id) as session:
        row = (
            await session.execute(
                text("select * from conversations where id = :id"), {"id": conversation_id}
            )
        ).one()
    return dict(row._mapping)
