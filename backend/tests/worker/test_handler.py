"""The worker's handling of one trigger: inbox, turn, outbox and delivery."""

from uuid import UUID

import pytest
from sqlalchemy import text

from frontdesk.agent.graph import AgentDeps
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.conversations import Receipt, transcript
from frontdesk.providers.ledger import ModelLedger, turn_costs
from frontdesk.providers.port import ModelRequest, ModelResponse
from frontdesk.providers.scripted import ScriptedProvider, calls, says
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import BARBERSHOP
from frontdesk.worker.handler import WorkerDeps, handle
from tests.support import IN_SCOPE, PRICES, RecordingSender, say
from tests.tools.conftest import NOW

CORTE = BARBERSHOP.service_id("Corte")
CAIO = BARBERSHOP.resource_id("Caio")


class BrokenProvider:
    name = "scripted"

    async def complete(self, _request: ModelRequest) -> ModelResponse:
        raise TimeoutError("model provider is down")


def worker(
    sessions: SessionFactory, sender: RecordingSender, *script: ModelResponse
) -> tuple[WorkerDeps, ScriptedProvider]:
    provider = ScriptedProvider(script)
    deps = WorkerDeps(
        sessions=sessions,
        agent=AgentDeps(
            sessions=sessions,
            provider=provider,
            model="scripted",
            ledger=ModelLedger(sessions, PRICES),
        ),
        senders={"webchat": sender},
        clock=lambda: NOW,
    )
    return deps, provider


def trigger_of(receipt: Receipt) -> Trigger:
    return Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id)


async def lines(sessions: SessionFactory, conversation_id: UUID) -> list[tuple[str, str]]:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        return [(line.author, line.text) for line in await transcript(session, conversation_id)]


async def test_ing_7_a_customer_message_becomes_a_reply_on_the_same_channel(
    sessions: SessionFactory,
) -> None:
    sender = RecordingSender()
    deps, _ = worker(sessions, sender, IN_SCOPE, says("Oi, Ana! Como posso ajudar?"))
    receipt = await say(sessions, "oi", "m1")

    await handle(deps, trigger_of(receipt))

    [reply] = sender.sent
    assert reply.text == "Oi, Ana! Como posso ajudar?"
    assert reply.channel == "webchat"
    assert reply.recipient_external_id == "Ana"
    assert await lines(sessions, receipt.conversation_id) == [
        ("customer", "oi"),
        ("agent", "Oi, Ana! Como posso ajudar?"),
    ]


async def test_ing_2_a_redelivered_message_is_stored_and_answered_once(
    sessions: SessionFactory,
) -> None:
    sender = RecordingSender()
    deps, _ = worker(sessions, sender, IN_SCOPE, says("Oi!"))

    first = await say(sessions, "oi", "m1")
    again = await say(sessions, "oi", "m1")
    await handle(deps, trigger_of(first))
    await handle(deps, trigger_of(again))

    assert (first.duplicate, again.duplicate) == (False, True)
    assert again.conversation_id == first.conversation_id
    assert len(sender.sent) == 1
    assert await lines(sessions, first.conversation_id) == [("customer", "oi"), ("agent", "Oi!")]


async def test_a_redelivery_of_an_unanswered_message_still_asks_for_a_turn(
    sessions: SessionFactory,
) -> None:
    sender = RecordingSender()
    deps, _ = worker(sessions, sender, IN_SCOPE, says("Oi!"))

    first = await say(sessions, "oi", "m1")
    unanswered = await say(sessions, "oi", "m1")
    await handle(deps, trigger_of(first))
    answered = await say(sessions, "oi", "m1")

    assert unanswered.pending is True
    assert answered.pending is False


async def test_a_trigger_with_nothing_pending_does_no_work(sessions: SessionFactory) -> None:
    sender = RecordingSender()
    deps, provider = worker(sessions, sender, IN_SCOPE, says("Oi!"))
    receipt = await say(sessions, "oi", "m1")
    await handle(deps, trigger_of(receipt))

    await handle(deps, trigger_of(receipt))

    assert len(provider.requests) == 2
    assert len(sender.sent) == 1


async def test_ing_5_messages_waiting_together_are_answered_in_one_turn(
    sessions: SessionFactory,
) -> None:
    sender = RecordingSender()
    deps, provider = worker(sessions, sender, IN_SCOPE, says("Temos corte e barba."))
    await say(sessions, "oi", "m1")
    receipt = await say(sessions, "quais serviços vocês têm?", "m2")

    await handle(deps, trigger_of(receipt))

    assert provider.requests[-1].messages[-1].content == "oi\nquais serviços vocês têm?"
    assert len(sender.sent) == 1


async def test_the_next_turn_sees_the_conversation_so_far(sessions: SessionFactory) -> None:
    sender = RecordingSender()
    deps, provider = worker(
        sessions, sender, IN_SCOPE, says("Oi! Quer agendar?"), IN_SCOPE, says("Qual horário?")
    )
    await handle(deps, trigger_of(await say(sessions, "oi", "m1")))

    await handle(deps, trigger_of(await say(sessions, "quero", "m2")))

    seen = [(message.role, message.content) for message in provider.requests[-1].messages]
    assert seen == [("user", "oi"), ("assistant", "Oi! Quer agendar?"), ("user", "quero")]


async def test_a_turn_that_died_is_resumed_and_writes_once(sessions: SessionFactory) -> None:
    book = calls(
        "create_booking",
        {"service_id": str(CORTE), "resource_id": str(CAIO), "starts_at": "2026-11-18T10:00:00"},
    )
    sender = RecordingSender()
    receipt = await say(sessions, "quero cortar às 10 com o Caio", "m1")
    dying, _ = worker(sessions, sender, IN_SCOPE, book)
    with pytest.raises(AssertionError, match="no scripted answer"):
        await handle(dying, trigger_of(receipt))

    retrying, _ = worker(sessions, sender, IN_SCOPE, book, says("Agendado para as 10h."))
    await handle(retrying, trigger_of(receipt))

    assert [message.text for message in sender.sent] == ["Agendado para as 10h."]
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        assert await session.scalar(text("select count(*) from bookings")) == 1
        assert await session.scalar(text("select count(*) from turns")) == 1


async def test_a_reply_that_could_not_be_sent_is_sent_later_without_a_new_turn(
    sessions: SessionFactory,
) -> None:
    receipt = await say(sessions, "oi", "m1")
    down = RecordingSender(failing=True)
    deps, provider = worker(sessions, down, IN_SCOPE, says("Oi!"))
    with pytest.raises(ConnectionError):
        await handle(deps, trigger_of(receipt))

    back = RecordingSender()
    recovered, _ = worker(sessions, back)
    await handle(recovered, trigger_of(receipt))

    assert [message.text for message in back.sent] == ["Oi!"]
    assert len(provider.requests) == 2


async def test_cst_1_every_model_call_of_a_turn_is_recorded_with_its_cost(
    sessions: SessionFactory,
) -> None:
    deps, _ = worker(
        sessions,
        RecordingSender(),
        IN_SCOPE,
        calls("list_services", {}),
        says("Temos corte, barba e corte e barba."),
    )
    receipt = await say(sessions, "o que vocês fazem?", "m1")

    await handle(deps, trigger_of(receipt))

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        costs = await turn_costs(session, receipt.conversation_id)
    assert [(call.node, call.input_tokens, call.output_tokens) for call in costs] == [
        ("classify", 100, 20),
        ("plan", 100, 20),
        ("plan", 100, 20),
    ]
    # 100 input tokens at USD 1.00 per million and 20 output tokens at USD 2.00.
    assert [call.cost_microusd for call in costs] == [140, 140, 140]
    assert {call.price_table_version for call in costs} == {"test"}


async def test_a_failing_provider_leaves_the_message_waiting(sessions: SessionFactory) -> None:
    sender = RecordingSender()
    deps, _ = worker(sessions, sender)
    broken = WorkerDeps(
        sessions=sessions,
        agent=AgentDeps(
            sessions=sessions,
            provider=BrokenProvider(),
            model="scripted",
            ledger=ModelLedger(sessions, PRICES),
        ),
        senders=deps.senders,
        clock=deps.clock,
    )
    receipt = await say(sessions, "oi", "m1")

    with pytest.raises(TimeoutError):
        await handle(broken, trigger_of(receipt))

    assert sender.sent == []
    assert await lines(sessions, receipt.conversation_id) == [("customer", "oi")]


async def test_cst_4_a_sent_message_records_what_its_channel_charged(
    sessions: SessionFactory,
) -> None:
    deps, _ = worker(sessions, RecordingSender(), IN_SCOPE, says("Oi, Ana!"))
    receipt = await say(sessions, "oi", "m1")

    await handle(deps, trigger_of(receipt))

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        charged = await session.execute(
            text(
                "select channel_cost_micros, channel_cost_currency from messages "
                "where direction = 'out'"
            )
        )
    # The web chat charges nothing, and says so instead of leaving the cost unknown.
    assert charged.all() == [(0, "USD")]


async def test_a_reply_with_a_byte_the_database_refuses_is_still_delivered(
    sessions: SessionFactory,
) -> None:
    """Seen with a real model: a NUL inside the reply, and the turn failed at its last write."""
    sender = RecordingSender()
    deps, _ = worker(sessions, sender, IN_SCOPE, says("Oi\x00, Ana! Como posso ajudar?"))
    receipt = await say(sessions, "oi", "m1")

    await handle(deps, trigger_of(receipt))

    assert [reply.text for reply in sender.sent] == ["Oi, Ana! Como posso ajudar?"]
    assert await lines(sessions, receipt.conversation_id) == [
        ("customer", "oi"),
        ("agent", "Oi, Ana! Como posso ajudar?"),
    ]
