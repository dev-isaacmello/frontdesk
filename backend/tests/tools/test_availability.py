"""BOOK-2: availability returns only slots that can actually be booked."""

from datetime import date, datetime

from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.schedule import Availability
from frontdesk.seed import ARENA, BARBERSHOP
from frontdesk.tools.context import ToolContext
from frontdesk.tools.schedule import CheckAvailabilityInput, check_availability
from tests.tools.conftest import SAO_PAULO, context_for

WEDNESDAY = date(2026, 11, 18)
MONDAY = date(2026, 11, 23)
CORTE = BARBERSHOP.service_id("Corte")
CORTE_E_BARBA = BARBERSHOP.service_id("Corte e barba")
CAIO = BARBERSHOP.resource_id("Caio")


def hours(availability: Availability, resource: str) -> list[str]:
    [slots] = [r.starts_at for r in availability.resources if r.resource_name == resource]
    return [slot.strftime("%H:%M") for slot in slots]


async def check(
    sessions: SessionFactory, context: ToolContext, arguments: CheckAvailabilityInput
) -> Availability:
    async with tenant_transaction(sessions, context.tenant_id) as session:
        return await check_availability.run(context, arguments, session)


async def test_book_2_slots_follow_the_grid_inside_business_hours(
    sessions: SessionFactory, barbershop: ToolContext
) -> None:
    result = await check(
        sessions, barbershop, CheckAvailabilityInput(service_id=CORTE, date=WEDNESDAY)
    )

    assert result.status == "ok"
    assert [resource.resource_name for resource in result.resources] == ["Caio", "Renan"]
    caio = hours(result, "Caio")
    assert caio[:3] == ["09:00", "09:30", "10:00"]
    assert caio[-1] == "18:30"
    assert len(caio) == 20


async def test_book_2_a_slot_must_fit_the_whole_service_before_closing(
    sessions: SessionFactory, barbershop: ToolContext
) -> None:
    result = await check(
        sessions, barbershop, CheckAvailabilityInput(service_id=CORTE_E_BARBA, date=WEDNESDAY)
    )

    assert hours(result, "Caio")[-1] == "18:00"


async def test_book_2_a_closed_day_has_no_slots(
    sessions: SessionFactory, barbershop: ToolContext
) -> None:
    result = await check(
        sessions, barbershop, CheckAvailabilityInput(service_id=CORTE, date=MONDAY)
    )

    assert result.status == "closed"
    assert result.resources == []


async def test_book_2_slots_that_already_started_are_not_offered(sessions: SessionFactory) -> None:
    after_lunch = context_for(BARBERSHOP, now=datetime(2026, 11, 18, 14, 10, tzinfo=SAO_PAULO))

    result = await check(
        sessions, after_lunch, CheckAvailabilityInput(service_id=CORTE, date=WEDNESDAY)
    )

    assert hours(result, "Caio")[0] == "14:30"


async def test_book_2_availability_can_be_asked_for_one_resource(
    sessions: SessionFactory, barbershop: ToolContext
) -> None:
    result = await check(
        sessions,
        barbershop,
        CheckAvailabilityInput(service_id=CORTE, date=WEDNESDAY, resource_id=CAIO),
    )

    assert [resource.resource_name for resource in result.resources] == ["Caio"]


async def test_book_2_a_service_of_another_tenant_is_unknown(
    sessions: SessionFactory, barbershop: ToolContext
) -> None:
    result = await check(
        sessions,
        barbershop,
        CheckAvailabilityInput(service_id=ARENA.service_id("Society (1 hora)"), date=WEDNESDAY),
    )

    assert result.status == "unknown_service"
