"""Fixtures for tool tests: a fixed clock and a context per tenant."""

from dataclasses import replace
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.customers import ChannelIdentity, identify_customer
from frontdesk.seed import ARENA, BARBERSHOP, TenantSeed
from frontdesk.tools.context import ToolContext

SAO_PAULO = ZoneInfo("America/Sao_Paulo")

# A Wednesday morning, before either tenant opens.
NOW = datetime(2026, 11, 18, 7, 0, tzinfo=SAO_PAULO)


def local(day: int, hour: int, minute: int = 0) -> datetime:
    """A wall-clock time in November 2026, as a customer of either tenant would say it."""
    return datetime(2026, 11, day, hour, minute)  # noqa: DTZ001


def context_for(tenant: TenantSeed, now: datetime = NOW) -> ToolContext:
    return ToolContext(
        tenant_id=tenant.id, customer_id=uuid4(), now=now, idempotency_key=str(uuid4())
    )


@pytest.fixture
def barbershop() -> ToolContext:
    return context_for(BARBERSHOP)


@pytest.fixture
def arena() -> ToolContext:
    return context_for(ARENA)


async def customer_of(
    sessions: SessionFactory, tenant: TenantSeed, name: str, now: datetime = NOW
) -> ToolContext:
    """The context of a customer who reached the tenant through the web chat."""
    identity = ChannelIdentity(channel="webchat", external_id=name, display_name=name)
    async with tenant_transaction(sessions, tenant.id) as session:
        customer_id = await identify_customer(session, tenant.id, identity)
    return ToolContext(
        tenant_id=tenant.id, customer_id=customer_id, now=now, idempotency_key=str(uuid4())
    )


def another_call(context: ToolContext) -> ToolContext:
    """The same customer making a new tool call, which carries a new idempotency key."""
    return replace(context, idempotency_key=str(uuid4()))
