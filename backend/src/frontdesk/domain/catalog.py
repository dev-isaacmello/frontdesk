"""Services and what they cost at a given time of day."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import time
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import Service, ServicePrice


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True)


class PriceWindow(_Result):
    starts_at: time
    price_cents: int


class ServiceInfo(_Result):
    id: UUID
    name: str
    duration_minutes: int
    prices: list[PriceWindow]

    def price_at(self, at: time) -> int:
        """The price of the latest window that has started by `at`."""
        started = [window for window in self.prices if window.starts_at <= at]
        return started[-1].price_cents


class ServiceList(_Result):
    services: list[ServiceInfo]


class QuoteItem(_Result):
    service_id: UUID
    name: str
    price_cents: int


class Quote(_Result):
    items: list[QuoteItem]
    total_cents: int
    unknown_service_ids: list[UUID]


async def list_services(session: AsyncSession) -> list[ServiceInfo]:
    services = (await session.scalars(select(Service).order_by(Service.name))).all()
    prices = await session.scalars(
        select(ServicePrice).order_by(ServicePrice.service_id, ServicePrice.starts_at)
    )
    windows: dict[UUID, list[PriceWindow]] = defaultdict(list)
    for price in prices:
        windows[price.service_id].append(
            PriceWindow(starts_at=price.starts_at, price_cents=price.price_cents)
        )
    return [
        ServiceInfo(
            id=service.id,
            name=service.name,
            duration_minutes=service.duration_minutes,
            prices=windows[service.id],
        )
        for service in services
    ]


async def find_service(session: AsyncSession, service_id: UUID) -> ServiceInfo | None:
    return {service.id: service for service in await list_services(session)}.get(service_id)


async def quote(session: AsyncSession, service_ids: Sequence[UUID], at: time) -> Quote:
    known = {service.id: service for service in await list_services(session)}
    items = [
        QuoteItem(
            service_id=service_id,
            name=known[service_id].name,
            price_cents=known[service_id].price_at(at),
        )
        for service_id in service_ids
        if service_id in known
    ]
    return Quote(
        items=items,
        total_cents=sum(item.price_cents for item in items),
        unknown_service_ids=[service_id for service_id in service_ids if service_id not in known],
    )
