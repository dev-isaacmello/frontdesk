"""BOOK-1: a price is always quoted for a service at a specific time."""

from datetime import time

from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.seed import ARENA, BARBERSHOP
from frontdesk.tools.catalog import ListServicesInput, QuoteInput, list_services, quote
from frontdesk.tools.context import ToolContext
from tests.tools.conftest import local

SOCIETY = ARENA.service_id("Society (1 hora)")
CORTE = BARBERSHOP.service_id("Corte")
BARBA = BARBERSHOP.service_id("Barba")


async def test_book_1_services_are_listed_with_their_price_windows(
    sessions: SessionFactory, arena: ToolContext
) -> None:
    async with tenant_transaction(sessions, arena.tenant_id) as session:
        result = await list_services.run(arena, ListServicesInput(), session)

    assert [service.name for service in result.services] == ["Areia (1 hora)", "Society (1 hora)"]
    society = result.services[1]
    assert society.duration_minutes == 60
    assert [(price.starts_at, price.price_cents) for price in society.prices] == [
        (time(0, 0), 12000),
        (time(18, 0), 18000),
    ]


async def test_book_1_the_price_follows_the_time_of_day(
    sessions: SessionFactory, arena: ToolContext
) -> None:
    async with tenant_transaction(sessions, arena.tenant_id) as session:
        afternoon = await quote.run(
            arena, QuoteInput(service_ids=[SOCIETY], starts_at=local(18, 17)), session
        )
        at_the_change = await quote.run(
            arena, QuoteInput(service_ids=[SOCIETY], starts_at=local(18, 18)), session
        )
        evening = await quote.run(
            arena, QuoteInput(service_ids=[SOCIETY], starts_at=local(18, 21, 30)), session
        )

    assert afternoon.total_cents == 12000
    assert at_the_change.total_cents == 18000
    assert evening.total_cents == 18000


async def test_book_1_a_quote_adds_up_the_services_so_the_model_never_does(
    sessions: SessionFactory, barbershop: ToolContext
) -> None:
    async with tenant_transaction(sessions, barbershop.tenant_id) as session:
        result = await quote.run(
            barbershop, QuoteInput(service_ids=[CORTE, BARBA], starts_at=local(18, 14)), session
        )

    assert [(item.name, item.price_cents) for item in result.items] == [
        ("Corte", 4500),
        ("Barba", 3000),
    ]
    assert result.total_cents == 7500
    assert result.unknown_service_ids == []


async def test_book_1_a_service_of_another_tenant_is_unknown(
    sessions: SessionFactory, barbershop: ToolContext
) -> None:
    async with tenant_transaction(sessions, barbershop.tenant_id) as session:
        result = await quote.run(
            barbershop, QuoteInput(service_ids=[SOCIETY], starts_at=local(18, 14)), session
        )

    assert result.items == []
    assert result.total_cents == 0
    assert result.unknown_service_ids == [SOCIETY]
