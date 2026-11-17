"""Who a message comes from."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import Customer, CustomerIdentity

type Channel = Literal["webchat", "whatsapp"]


@dataclass(frozen=True)
class ChannelIdentity:
    channel: Channel
    external_id: str
    display_name: str | None = None
    phone: str | None = None


async def identify_customer(
    session: AsyncSession, tenant_id: UUID, identity: ChannelIdentity
) -> UUID:
    """Returns the customer behind a channel identity, creating both on first contact."""
    known = await _customer_of(session, identity)
    if known is not None:
        return known

    customer = Customer(tenant_id=tenant_id, display_name=identity.display_name)
    session.add(customer)
    await session.flush()
    linked = await session.scalar(
        insert(CustomerIdentity)
        .values(
            tenant_id=tenant_id,
            channel=identity.channel,
            external_id=identity.external_id,
            customer_id=customer.id,
            phone=identity.phone,
        )
        .on_conflict_do_nothing()
        .returning(CustomerIdentity.customer_id)
    )
    if linked is not None:
        return customer.id

    # Another transaction saw the same first message and linked the identity before us.
    await session.delete(customer)
    winner = await _customer_of(session, identity)
    assert winner is not None
    return winner


async def _customer_of(session: AsyncSession, identity: ChannelIdentity) -> UUID | None:
    return await session.scalar(
        select(CustomerIdentity.customer_id).where(
            CustomerIdentity.channel == identity.channel,
            CustomerIdentity.external_id == identity.external_id,
        )
    )
