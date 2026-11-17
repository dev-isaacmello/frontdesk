"""When a service can be booked."""

from collections import defaultdict
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select, union_all
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import (
    Booking,
    BusinessHours,
    Resource,
    ScheduleBlock,
    ServiceResource,
    Tenant,
)
from frontdesk.domain.catalog import ServiceInfo, find_service
from frontdesk.domain.tenants import timezone_of


class ResourceAvailability(BaseModel):
    model_config = ConfigDict(frozen=True)

    resource_id: UUID
    resource_name: str
    starts_at: list[datetime]


class Availability(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "closed", "unknown_service"]
    resources: list[ResourceAvailability] = []


async def availability(
    session: AsyncSession,
    tenant: Tenant,
    *,
    service_id: UUID,
    day: date,
    now: datetime,
    resource_id: UUID | None = None,
) -> Availability:
    service = await find_service(session, service_id)
    if service is None:
        return Availability(status="unknown_service")

    starts = [start for start in await slot_starts(session, tenant, service, day) if start > now]
    if not starts:
        return Availability(status="closed")

    duration = timedelta(minutes=service.duration_minutes)
    busy = await _busy(session, Range(starts[0], starts[-1] + duration))
    return Availability(
        status="ok",
        resources=[
            ResourceAvailability(
                resource_id=resource.id,
                resource_name=resource.name,
                starts_at=[
                    start
                    for start in starts
                    if not _overlaps(busy[resource.id], Range(start, start + duration))
                ],
            )
            for resource in await resources_for(session, service_id, resource_id)
        ],
    )


async def resources_for(
    session: AsyncSession, service_id: UUID, resource_id: UUID | None = None
) -> list[Resource]:
    """The resources that deliver a service, optionally narrowed to one of them."""
    query = (
        select(Resource)
        .join(ServiceResource, ServiceResource.resource_id == Resource.id)
        .where(ServiceResource.service_id == service_id)
        .order_by(Resource.name)
    )
    if resource_id is not None:
        query = query.where(Resource.id == resource_id)
    return list(await session.scalars(query))


async def slot_starts(
    session: AsyncSession, tenant: Tenant, service: ServiceInfo, day: date
) -> list[datetime]:
    """Every start time the tenant's hours allow for a service on a day, taken or not."""
    hours = await session.get(BusinessHours, (tenant.id, day.isoweekday()))
    return [] if hours is None else list(_grid(tenant, hours, service, day))


async def is_blocked(session: AsyncSession, resource_id: UUID, during: Range[datetime]) -> bool:
    blocks = await session.scalars(
        select(ScheduleBlock.id)
        .where(ScheduleBlock.resource_id == resource_id, ScheduleBlock.during.overlaps(during))
        .limit(1)
    )
    return blocks.first() is not None


async def _busy(
    session: AsyncSession, window: Range[datetime]
) -> dict[UUID, list[Range[datetime]]]:
    """Confirmed bookings and blocks that touch a window, by resource."""
    bookings = select(Booking.resource_id, Booking.during).where(
        Booking.status == "confirmed", Booking.during.overlaps(window)
    )
    blocks = select(ScheduleBlock.resource_id, ScheduleBlock.during).where(
        ScheduleBlock.during.overlaps(window)
    )
    busy: dict[UUID, list[Range[datetime]]] = defaultdict(list)
    for resource_id, during in await session.execute(union_all(bookings, blocks)):
        busy[resource_id].append(during)
    return busy


def _overlaps(busy: list[Range[datetime]], candidate: Range[datetime]) -> bool:
    return any(candidate.overlaps(period) for period in busy)


def _grid(
    tenant: Tenant, hours: BusinessHours, service: ServiceInfo, day: date
) -> Iterator[datetime]:
    """Start times on the tenant's grid that leave room for the service before closing."""
    timezone = timezone_of(tenant)
    start = datetime.combine(day, hours.opens, tzinfo=timezone)
    closes = datetime.combine(day, hours.closes, tzinfo=timezone)
    duration = timedelta(minutes=service.duration_minutes)
    step = timedelta(minutes=tenant.slot_minutes)
    while start + duration <= closes:
        yield start
        start += step
