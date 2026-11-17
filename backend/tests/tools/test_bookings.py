"""BOOK-3 to BOOK-6: creating, listing, cancelling and rescheduling bookings."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.dialects.postgresql import Range

from frontdesk.db.models import ScheduleBlock
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.bookings import Booked, BookingInfo, Cancelled, Refused, Rescheduled
from frontdesk.seed import ARENA, BARBERSHOP
from frontdesk.tools.bookings import (
    CancelBookingInput,
    CreateBookingInput,
    ListCustomerBookingsInput,
    RescheduleBookingInput,
    cancel_booking,
    create_booking,
    list_customer_bookings,
    reschedule_booking,
)
from frontdesk.tools.context import ToolContext
from frontdesk.tools.schedule import CheckAvailabilityInput, check_availability
from tests.tools.conftest import SAO_PAULO, another_call, customer_of, local

WEDNESDAY = date(2026, 11, 18)
CORTE = BARBERSHOP.service_id("Corte")
CORTE_E_BARBA = BARBERSHOP.service_id("Corte e barba")
CAIO = BARBERSHOP.resource_id("Caio")
SOCIETY = ARENA.service_id("Society (1 hora)")
SOCIETY_COURT = ARENA.resource_id("Quadra Society")
SAND_COURT = ARENA.resource_id("Quadra de Areia")


async def book(
    sessions: SessionFactory, customer: ToolContext, arguments: CreateBookingInput
) -> Booked | Refused:
    async with tenant_transaction(sessions, customer.tenant_id) as session:
        return await create_booking.run(customer, arguments, session)


async def book_corte_with_caio(
    sessions: SessionFactory, customer: ToolContext, hour: int, minute: int = 0
) -> Booked | Refused:
    return await book(
        sessions,
        customer,
        CreateBookingInput(service_id=CORTE, resource_id=CAIO, starts_at=local(18, hour, minute)),
    )


async def bookings_of(sessions: SessionFactory, customer: ToolContext) -> list[BookingInfo]:
    async with tenant_transaction(sessions, customer.tenant_id) as session:
        result = await list_customer_bookings.run(customer, ListCustomerBookingsInput(), session)
    return result.bookings


async def free_hours(
    sessions: SessionFactory, customer: ToolContext, service_id: UUID, resource: str
) -> list[str]:
    async with tenant_transaction(sessions, customer.tenant_id) as session:
        result = await check_availability.run(
            customer, CheckAvailabilityInput(service_id=service_id, date=WEDNESDAY), session
        )
    [slots] = [r.starts_at for r in result.resources if r.resource_name == resource]
    return [slot.strftime("%H:%M") for slot in slots]


async def test_book_3_a_free_slot_is_booked_at_the_price_of_its_time(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, ARENA, "Ana")

    result = await book(
        sessions,
        ana,
        CreateBookingInput(service_id=SOCIETY, resource_id=SOCIETY_COURT, starts_at=local(18, 19)),
    )

    assert isinstance(result, Booked)
    assert result.booking.service_name == "Society (1 hora)"
    assert result.booking.resource_name == "Quadra Society"
    assert result.booking.starts_at == datetime(2026, 11, 18, 19, 0, tzinfo=SAO_PAULO)
    assert result.booking.ends_at == datetime(2026, 11, 18, 20, 0, tzinfo=SAO_PAULO)
    assert result.booking.price_cents == 18000


async def test_book_6_a_local_time_is_stored_as_the_matching_utc_instant(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")

    result = await book_corte_with_caio(sessions, ana, 14)

    assert isinstance(result, Booked)
    assert result.booking.starts_at == datetime(2026, 11, 18, 17, 0, tzinfo=UTC)
    assert result.booking.starts_at.utcoffset() == SAO_PAULO.utcoffset(datetime(2026, 11, 18))  # noqa: DTZ001


async def test_book_3_a_taken_slot_is_refused(sessions: SessionFactory) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    bruno = await customer_of(sessions, BARBERSHOP, "Bruno")
    await book_corte_with_caio(sessions, ana, 10)

    result = await book_corte_with_caio(sessions, bruno, 10)

    assert result == Refused(reason="slot_taken")


async def test_book_3_a_longer_service_cannot_overlap_an_existing_booking(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    bruno = await customer_of(sessions, BARBERSHOP, "Bruno")
    await book_corte_with_caio(sessions, ana, 10)

    result = await book(
        sessions,
        bruno,
        CreateBookingInput(service_id=CORTE_E_BARBA, resource_id=CAIO, starts_at=local(18, 9, 30)),
    )

    assert result == Refused(reason="slot_taken")


async def test_book_3_concurrent_attempts_on_one_slot_book_it_once(
    sessions: SessionFactory,
) -> None:
    customers = [await customer_of(sessions, BARBERSHOP, f"Cliente {n}") for n in range(5)]

    results = await asyncio.gather(
        *(book_corte_with_caio(sessions, customer, 11) for customer in customers)
    )

    assert sorted(type(result).__name__ for result in results) == [
        "Booked",
        "Refused",
        "Refused",
        "Refused",
        "Refused",
    ]


async def test_book_4_a_retry_with_the_same_key_returns_the_first_booking(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")

    first = await book_corte_with_caio(sessions, ana, 15)
    retry = await book_corte_with_caio(sessions, ana, 15)

    assert isinstance(first, Booked)
    assert retry == first
    assert len(await bookings_of(sessions, ana)) == 1


async def test_book_2_a_booked_slot_leaves_availability(sessions: SessionFactory) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    await book_corte_with_caio(sessions, ana, 10)

    caio = await free_hours(sessions, ana, CORTE_E_BARBA, "Caio")
    renan = await free_hours(sessions, ana, CORTE_E_BARBA, "Renan")

    assert caio[:3] == ["09:00", "10:30", "11:00"]
    assert renan[:3] == ["09:00", "09:30", "10:00"]


async def test_book_2_blocked_time_is_neither_offered_nor_bookable(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    lunch = Range(
        datetime(2026, 11, 18, 12, 0, tzinfo=SAO_PAULO),
        datetime(2026, 11, 18, 13, 0, tzinfo=SAO_PAULO),
    )
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        session.add(ScheduleBlock(tenant_id=BARBERSHOP.id, resource_id=CAIO, during=lunch))

    offered = await free_hours(sessions, ana, CORTE, "Caio")
    result = await book_corte_with_caio(sessions, ana, 12, 30)

    assert "11:30" in offered
    assert "12:00" not in offered
    assert "12:30" not in offered
    assert "13:00" in offered
    assert result == Refused(reason="slot_taken")


async def test_book_3_times_that_are_not_slots_are_refused(sessions: SessionFactory) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")

    after_closing = await book_corte_with_caio(sessions, ana, 19)
    off_the_grid = await book_corte_with_caio(sessions, ana, 14, 10)
    closed_day = await book(
        sessions,
        ana,
        CreateBookingInput(service_id=CORTE, resource_id=CAIO, starts_at=local(23, 10)),
    )

    assert after_closing == Refused(reason="not_a_slot")
    assert off_the_grid == Refused(reason="not_a_slot")
    assert closed_day == Refused(reason="not_a_slot")


async def test_book_3_a_time_in_the_past_is_refused(sessions: SessionFactory) -> None:
    afternoon = datetime(2026, 11, 18, 15, 0, tzinfo=SAO_PAULO)
    ana = await customer_of(sessions, BARBERSHOP, "Ana", now=afternoon)

    result = await book_corte_with_caio(sessions, ana, 10)

    assert result == Refused(reason="in_the_past")


async def test_book_3_a_resource_that_does_not_deliver_the_service_is_refused(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, ARENA, "Ana")

    wrong_court = await book(
        sessions,
        ana,
        CreateBookingInput(service_id=SOCIETY, resource_id=SAND_COURT, starts_at=local(18, 19)),
    )
    other_tenant = await book(
        sessions,
        ana,
        CreateBookingInput(service_id=CORTE, resource_id=CAIO, starts_at=local(18, 10)),
    )

    assert wrong_court == Refused(reason="resource_cannot_do_service")
    assert other_tenant == Refused(reason="unknown_service")


async def test_book_5_a_customer_lists_only_their_own_upcoming_bookings(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    bruno = await customer_of(sessions, BARBERSHOP, "Bruno")
    await book_corte_with_caio(sessions, ana, 16)
    await book_corte_with_caio(sessions, another_call(ana), 10)
    await book_corte_with_caio(sessions, bruno, 11)

    mine = await bookings_of(sessions, ana)
    later = await bookings_of(sessions, replace(ana, now=local(18, 12).replace(tzinfo=SAO_PAULO)))

    assert [booking.starts_at.strftime("%H:%M") for booking in mine] == ["10:00", "16:00"]
    assert [booking.starts_at.strftime("%H:%M") for booking in later] == ["16:00"]


async def test_book_5_cancelling_frees_the_slot(sessions: SessionFactory) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    bruno = await customer_of(sessions, BARBERSHOP, "Bruno")
    booked = await book_corte_with_caio(sessions, ana, 10)
    assert isinstance(booked, Booked)
    arguments = CancelBookingInput(booking_id=booked.booking.booking_id)

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        cancelled = await cancel_booking.run(ana, arguments, session)
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        again = await cancel_booking.run(ana, arguments, session)
    rebooked = await book_corte_with_caio(sessions, bruno, 10)

    assert cancelled == Cancelled(booking=booked.booking)
    assert again == Refused(reason="already_cancelled")
    assert await bookings_of(sessions, ana) == []
    assert isinstance(rebooked, Booked)


async def test_book_5_a_customer_cannot_cancel_or_move_a_booking_of_another(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    bruno = await customer_of(sessions, BARBERSHOP, "Bruno")
    booked = await book_corte_with_caio(sessions, ana, 10)
    assert isinstance(booked, Booked)
    booking_id = booked.booking.booking_id

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        cancelled = await cancel_booking.run(
            bruno, CancelBookingInput(booking_id=booking_id), session
        )
        moved = await reschedule_booking.run(
            bruno, RescheduleBookingInput(booking_id=booking_id, starts_at=local(18, 15)), session
        )

    assert cancelled == Refused(reason="not_found")
    assert moved == Refused(reason="not_found")
    assert await bookings_of(sessions, ana) == [booked.booking]


async def test_book_5_rescheduling_moves_the_booking_and_reprices_it(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, ARENA, "Ana")
    booked = await book(
        sessions,
        ana,
        CreateBookingInput(service_id=SOCIETY, resource_id=SOCIETY_COURT, starts_at=local(18, 17)),
    )
    assert isinstance(booked, Booked)
    assert booked.booking.price_cents == 12000

    async with tenant_transaction(sessions, ARENA.id) as session:
        moved = await reschedule_booking.run(
            ana,
            RescheduleBookingInput(booking_id=booked.booking.booking_id, starts_at=local(18, 20)),
            session,
        )

    assert isinstance(moved, Rescheduled)
    assert moved.booking.booking_id == booked.booking.booking_id
    assert moved.booking.starts_at == datetime(2026, 11, 18, 20, 0, tzinfo=SAO_PAULO)
    assert moved.booking.price_cents == 18000
    assert await bookings_of(sessions, ana) == [moved.booking]


async def test_book_5_rescheduling_onto_a_taken_slot_changes_nothing(
    sessions: SessionFactory,
) -> None:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    bruno = await customer_of(sessions, BARBERSHOP, "Bruno")
    mine = await book_corte_with_caio(sessions, ana, 10)
    await book_corte_with_caio(sessions, bruno, 11)
    assert isinstance(mine, Booked)

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        moved = await reschedule_booking.run(
            ana,
            RescheduleBookingInput(booking_id=mine.booking.booking_id, starts_at=local(18, 11)),
            session,
        )

    assert moved == Refused(reason="slot_taken")
    assert await bookings_of(sessions, ana) == [mine.booking]
