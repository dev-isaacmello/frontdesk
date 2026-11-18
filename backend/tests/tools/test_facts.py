"""What the tools feed the guardrail: every value in an input or an output, typed."""

import datetime as dt
from uuid import uuid4
from zoneinfo import ZoneInfo

from frontdesk.domain.bookings import BookingInfo, BookingList
from frontdesk.domain.catalog import PriceWindow, Quote, QuoteItem, ServiceInfo
from frontdesk.guardrail import Count, Day, Duration, Money, TimeOfDay
from frontdesk.tools.bookings import CreateBookingInput
from frontdesk.tools.facts import facts_of
from frontdesk.tools.schedule import CheckAvailabilityInput

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


def test_grd_2_a_quote_gives_each_price_and_the_total() -> None:
    quote = Quote(
        items=[
            QuoteItem(service_id=uuid4(), name="Corte", price_cents=4500),
            QuoteItem(service_id=uuid4(), name="Barba", price_cents=3000),
        ],
        total_cents=7500,
        unknown_service_ids=[],
    )

    facts = facts_of(quote, SAO_PAULO)

    assert {Money(4500), Money(3000), Money(7500)} <= set(facts)
    assert Count(2) in facts


def test_grd_2_a_booking_gives_its_day_and_times_in_the_tenant_clock() -> None:
    booking = BookingInfo(
        booking_id=uuid4(),
        service_name="Corte",
        resource_name="Caio",
        starts_at=dt.datetime(2026, 11, 18, 13, 0, tzinfo=dt.UTC),
        ends_at=dt.datetime(2026, 11, 18, 13, 30, tzinfo=dt.UTC),
        price_cents=4500,
    )

    facts = set(facts_of(BookingList(bookings=[booking]), SAO_PAULO))

    assert {Day(dt.date(2026, 11, 18)), TimeOfDay(10, 0), TimeOfDay(10, 30), Money(4500)} <= facts
    assert Count(1) in facts


def test_grd_2_a_service_gives_its_duration_and_its_price_windows() -> None:
    service = ServiceInfo(
        id=uuid4(),
        name="Quadra Society",
        duration_minutes=60,
        prices=[
            PriceWindow(starts_at=dt.time(0, 0), price_cents=12000),
            PriceWindow(starts_at=dt.time(18, 0), price_cents=18000),
        ],
    )

    facts = set(facts_of(service, SAO_PAULO))

    assert {Duration(60), Money(12000), Money(18000), TimeOfDay(18, 0)} <= facts


def test_grd_2_what_the_model_asked_a_tool_for_is_a_fact_too() -> None:
    asked = CheckAvailabilityInput(service_id=uuid4(), date=dt.date(2026, 11, 20))
    placed = CreateBookingInput(
        service_id=uuid4(),
        resource_id=uuid4(),
        starts_at=dt.datetime(2026, 11, 20, 15, 0),  # noqa: DTZ001  naive is the case
    )

    assert Day(dt.date(2026, 11, 20)) in facts_of(asked, SAO_PAULO)
    # A time without an offset is already on the tenant's clock.
    assert {Day(dt.date(2026, 11, 20)), TimeOfDay(15, 0)} <= set(facts_of(placed, SAO_PAULO))


def test_ids_names_and_flags_are_not_facts() -> None:
    quote = Quote(items=[], total_cents=0, unknown_service_ids=[uuid4()])

    assert set(facts_of(quote, SAO_PAULO)) == {Money(0), Count(0), Count(1)}
