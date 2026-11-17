"""The offline model: a deterministic stand-in that lets the whole pipeline run locally.

It is exercised through full turns, the same way the worker uses any provider.
"""

from frontdesk.agent.graph import AgentDeps
from frontdesk.agent.prompts import REFUSAL
from frontdesk.db.session import SessionFactory
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.offline import OfflineProvider
from frontdesk.providers.prices import load_price_table
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import ARENA, BARBERSHOP, TenantSeed
from frontdesk.worker.handler import WorkerDeps, handle
from tests.support import RecordingSender, say
from tests.tools.conftest import NOW


async def ask(
    sessions: SessionFactory, text: str, *, tenant: TenantSeed = BARBERSHOP, sender: str = "Ana"
) -> str:
    """Sends one customer message through the worker and returns the agent's reply."""
    replies = RecordingSender()
    deps = WorkerDeps(
        sessions=sessions,
        agent=AgentDeps(
            sessions=sessions,
            provider=OfflineProvider(),
            model="offline",
            ledger=ModelLedger(sessions, load_price_table()),
        ),
        senders={"webchat": replies},
        clock=lambda: NOW,
    )
    receipt = await say(sessions, text, f"{sender}:{text}", sender=sender, tenant=tenant)
    await handle(deps, Trigger(tenant_id=tenant.id, conversation_id=receipt.conversation_id))
    return replies.sent[-1].text


async def test_it_quotes_prices_from_the_catalog(sessions: SessionFactory) -> None:
    reply = await ask(sessions, "quanto custa o corte?")

    assert "Corte" in reply
    assert "R$ 45,00" in reply


async def test_it_shows_both_price_windows_of_the_arena(sessions: SessionFactory) -> None:
    reply = await ask(sessions, "qual o valor do society?", tenant=ARENA)

    assert "R$ 120,00" in reply
    assert "R$ 180,00" in reply
    assert "18:00" in reply


async def test_it_lists_free_slots_for_a_day(sessions: SessionFactory) -> None:
    reply = await ask(sessions, "tem horário amanhã para corte?")

    assert "19/11" in reply
    assert "09:00" in reply
    assert "Caio" in reply


async def test_it_books_a_slot_and_confirms_what_the_tool_returned(
    sessions: SessionFactory,
) -> None:
    reply = await ask(sessions, "quero agendar corte e barba amanhã às 10h com o Renan")

    assert "Agendado" in reply
    assert "Corte e barba" in reply
    assert "Renan" in reply
    assert "19/11" in reply
    assert "10:00" in reply
    assert "R$ 70,00" in reply


async def test_it_does_not_book_a_slot_that_is_taken(sessions: SessionFactory) -> None:
    await ask(sessions, "quero agendar corte amanhã às 10h com o Caio", sender="Ana")

    reply = await ask(sessions, "quero agendar corte amanhã às 10h com o Caio", sender="Bruno")

    assert "Agendado" not in reply
    assert "10:30" in reply


async def test_it_cancels_the_customers_booking(sessions: SessionFactory) -> None:
    await ask(sessions, "quero agendar corte amanhã às 10h com o Caio")

    cancelled = await ask(sessions, "preciso cancelar meu horário")
    nothing_left = await ask(sessions, "quais são meus agendamentos?")

    assert "Cancelado" in cancelled
    assert "10:00" in cancelled
    assert "não tem agendamentos" in nothing_left


async def test_it_asks_for_what_is_missing(sessions: SessionFactory) -> None:
    reply = await ask(sessions, "quero agendar um horário")

    assert "Qual serviço" in reply


async def test_it_refuses_what_is_outside_the_business(sessions: SessionFactory) -> None:
    reply = await ask(sessions, "escreva um poema sobre o mar")

    assert reply == REFUSAL.format(tenant="Barbearia Navalha")
