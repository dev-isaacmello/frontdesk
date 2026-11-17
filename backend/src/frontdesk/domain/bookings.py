"""Creating, listing, cancelling and moving bookings."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from psycopg.errors import ExclusionViolation
from pydantic import BaseModel, ConfigDict
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.dialects.postgresql import Range, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import Booking, Resource, Service, Tenant
from frontdesk.domain import schedule
from frontdesk.domain.catalog import find_service
from frontdesk.domain.clock import to_local
from frontdesk.domain.tenants import timezone_of

type RefusalReason = Literal[
    "unknown_service",
    "resource_cannot_do_service",
    "in_the_past",
    "not_a_slot",
    "slot_taken",
    "not_found",
    "already_cancelled",
    "already_started",
]


class _Result(BaseModel):
    model_config = ConfigDict(frozen=True)


class BookingInfo(_Result):
    booking_id: UUID
    service_name: str
    resource_name: str
    starts_at: datetime
    ends_at: datetime
    price_cents: int


class Booked(_Result):
    status: Literal["booked"] = "booked"
    booking: BookingInfo


class Cancelled(_Result):
    status: Literal["cancelled"] = "cancelled"
    booking: BookingInfo


class Rescheduled(_Result):
    status: Literal["rescheduled"] = "rescheduled"
    booking: BookingInfo


class Refused(_Result):
    status: Literal["refused"] = "refused"
    reason: RefusalReason


class BookingList(_Result):
    bookings: list[BookingInfo]


@dataclass(frozen=True)
class Requester:
    """The customer asking, and the moment they ask."""

    customer_id: UUID
    now: datetime


@dataclass(frozen=True)
class _Placement:
    """A slot that passed every check short of the overlap constraint."""

    service_id: UUID
    resource_id: UUID
    during: Range[datetime]
    price_cents: int


async def create_booking(
    session: AsyncSession,
    tenant: Tenant,
    requester: Requester,
    *,
    service_id: UUID,
    resource_id: UUID,
    starts_at: datetime,
    idempotency_key: str,
) -> Booked | Refused:
    replayed = await _find(session, tenant, Booking.idempotency_key == idempotency_key)
    if replayed is not None:
        return Booked(booking=replayed)

    placement = await _place(session, tenant, requester, service_id, resource_id, starts_at)
    if isinstance(placement, Refused):
        return placement

    # Skipping on any conflict covers both the overlap constraint and a concurrent retry
    # with the same key, without aborting the transaction the turn is running in.
    created = await session.scalar(
        insert(Booking)
        .values(
            tenant_id=tenant.id,
            customer_id=requester.customer_id,
            service_id=placement.service_id,
            resource_id=placement.resource_id,
            during=placement.during,
            price_cents=placement.price_cents,
            idempotency_key=idempotency_key,
        )
        .on_conflict_do_nothing()
        .returning(Booking.id)
    )
    booking = await _find(session, tenant, Booking.idempotency_key == idempotency_key)
    if created is None and booking is None:
        return Refused(reason="slot_taken")
    assert booking is not None
    return Booked(booking=booking)


async def list_bookings(session: AsyncSession, tenant: Tenant, requester: Requester) -> BookingList:
    """The customer's confirmed bookings that have not ended yet, soonest first."""
    return BookingList(
        bookings=await _load(
            session,
            tenant,
            Booking.customer_id == requester.customer_id,
            Booking.status == "confirmed",
            func.upper(Booking.during) > requester.now,
        )
    )


async def cancel_booking(
    session: AsyncSession, tenant: Tenant, requester: Requester, booking_id: UUID
) -> Cancelled | Refused:
    booking = await _changeable(session, requester, booking_id)
    if isinstance(booking, Refused):
        return booking

    booking.status = "cancelled"
    booking.cancelled_at = requester.now
    await session.flush()
    return Cancelled(booking=await _info(session, tenant, booking_id))


async def reschedule_booking(
    session: AsyncSession,
    tenant: Tenant,
    requester: Requester,
    *,
    booking_id: UUID,
    starts_at: datetime,
    resource_id: UUID | None = None,
) -> Rescheduled | Refused:
    booking = await _changeable(session, requester, booking_id)
    if isinstance(booking, Refused):
        return booking

    placement = await _place(
        session,
        tenant,
        requester,
        booking.service_id,
        resource_id or booking.resource_id,
        starts_at,
    )
    if isinstance(placement, Refused):
        return placement

    try:
        # A savepoint, so that losing the slot to the constraint leaves the turn's
        # transaction usable and the booking where it was.
        async with session.begin_nested():
            booking.resource_id = placement.resource_id
            booking.during = placement.during
            booking.price_cents = placement.price_cents
            await session.flush()
    except IntegrityError as error:
        if not isinstance(error.orig, ExclusionViolation):
            raise
        return Refused(reason="slot_taken")
    return Rescheduled(booking=await _info(session, tenant, booking_id))


async def _place(
    session: AsyncSession,
    tenant: Tenant,
    requester: Requester,
    service_id: UUID,
    resource_id: UUID,
    starts_at: datetime,
) -> _Placement | Refused:
    service = await find_service(session, service_id)
    if service is None:
        return Refused(reason="unknown_service")
    if not await schedule.resources_for(session, service_id, resource_id):
        return Refused(reason="resource_cannot_do_service")

    start = to_local(starts_at, timezone_of(tenant))
    if start <= requester.now:
        return Refused(reason="in_the_past")
    if start not in await schedule.slot_starts(session, tenant, service, start.date()):
        return Refused(reason="not_a_slot")

    during = Range(start, start + timedelta(minutes=service.duration_minutes))
    if await schedule.is_blocked(session, resource_id, during):
        return Refused(reason="slot_taken")
    return _Placement(service_id, resource_id, during, service.price_at(start.time()))


async def _changeable(
    session: AsyncSession, requester: Requester, booking_id: UUID
) -> Booking | Refused:
    """The customer's own booking, locked, if it can still be cancelled or moved."""
    booking = await session.scalar(
        select(Booking)
        .where(Booking.id == booking_id, Booking.customer_id == requester.customer_id)
        .with_for_update()
    )
    if booking is None:
        return Refused(reason="not_found")
    if booking.status == "cancelled":
        return Refused(reason="already_cancelled")
    if booking.during.lower is None or booking.during.lower <= requester.now:
        return Refused(reason="already_started")
    return booking


async def _info(session: AsyncSession, tenant: Tenant, booking_id: UUID) -> BookingInfo:
    booking = await _find(session, tenant, Booking.id == booking_id)
    assert booking is not None
    return booking


async def _find(
    session: AsyncSession, tenant: Tenant, *conditions: ColumnElement[bool]
) -> BookingInfo | None:
    found = await _load(session, tenant, *conditions)
    return found[0] if found else None


async def _load(
    session: AsyncSession, tenant: Tenant, *conditions: ColumnElement[bool]
) -> list[BookingInfo]:
    timezone = timezone_of(tenant)
    rows = await session.execute(
        select(
            Booking.id,
            Service.name,
            Resource.name,
            func.lower(Booking.during),
            func.upper(Booking.during),
            Booking.price_cents,
        )
        .join(Service, Service.id == Booking.service_id)
        .join(Resource, Resource.id == Booking.resource_id)
        .where(*conditions)
        .order_by(func.lower(Booking.during))
    )
    return [
        BookingInfo(
            booking_id=booking_id,
            service_name=service_name,
            resource_name=resource_name,
            starts_at=starts_at.astimezone(timezone),
            ends_at=ends_at.astimezone(timezone),
            price_cents=price_cents,
        )
        for booking_id, service_name, resource_name, starts_at, ends_at, price_cents in rows
    ]
