"""The worker loop: conversations leased from the queue, handled and acknowledged."""

import asyncio
import logging
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from frontdesk.agent.graph import AgentDeps
from frontdesk.agent.prompts import HANDOFF_NOTICE
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.conversations import open_turn
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.offline import OfflineProvider
from frontdesk.providers.port import ModelProvider, ModelRequest, ModelResponse
from frontdesk.providers.prices import load_price_table
from frontdesk.queue.port import Delivery, TriggerQueue
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import BARBERSHOP
from frontdesk.worker.handler import WorkerDeps
from frontdesk.worker.loop import backoff_seconds, process_next, run
from tests.fakes import InMemoryLease, InMemoryTriggerQueue, waiting_triggers
from tests.support import RecordingSender, conversation_row, say
from tests.tools.conftest import NOW

SECRET_TEXT = "oi, aqui é a Mariana Albuquerque, quanto custa o corte?"


class BrokenProvider:
    name = "broken"

    async def complete(self, _request: ModelRequest) -> ModelResponse:
        raise TimeoutError("model provider is down")


def worker(
    sessions: SessionFactory, sender: RecordingSender, provider: ModelProvider | None = None
) -> WorkerDeps:
    return WorkerDeps(
        sessions=sessions,
        agent=AgentDeps(
            sessions=sessions,
            provider=provider or OfflineProvider(),
            model="offline",
            ledger=ModelLedger(sessions, load_price_table()),
        ),
        senders={"webchat": sender},
        clock=lambda: NOW,
    )


async def enqueue(sessions: SessionFactory, queue: TriggerQueue, text_: str, sender: str) -> None:
    receipt = await say(sessions, text_, f"{sender}-1", sender=sender)
    await queue.send(
        Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id),
        deduplication_id=f"{sender}-1",
    )


def no_pause(_attempt: int) -> float:
    return 0


async def test_each_waiting_conversation_is_handled_and_acknowledged(
    sessions: SessionFactory, queue: TriggerQueue
) -> None:
    sender = RecordingSender()
    await enqueue(sessions, queue, "quanto custa o corte?", "Ana")
    await enqueue(sessions, queue, "quanto custa a barba?", "Bruno")

    handled = [
        await process_next(worker(sessions, sender), queue, wait_seconds=0) for _ in range(3)
    ]

    assert handled == [1, 1, 0]
    assert sorted(message.recipient_external_id for message in sender.sent) == ["Ana", "Bruno"]
    assert await waiting_triggers(queue) == []


async def test_a_trigger_that_fails_is_retried_and_the_others_are_handled(
    sessions: SessionFactory, queue: TriggerQueue
) -> None:
    await enqueue(sessions, queue, "quanto custa o corte?", "Ana")
    down = RecordingSender(failing=True)

    failed = await process_next(worker(sessions, down), queue, wait_seconds=0, pause=no_pause)
    lost = Trigger(tenant_id=BARBERSHOP.id, conversation_id=BARBERSHOP.id)
    await queue.send(lost, deduplication_id="unknown-conversation")
    back = RecordingSender()
    recovered = [
        await process_next(worker(sessions, back), queue, wait_seconds=0, pause=no_pause)
        for _ in range(2)
    ]

    assert failed == 0
    assert recovered == [1, 1]
    assert [message.recipient_external_id for message in back.sent] == ["Ana"]


async def test_a_trigger_that_never_succeeds_is_set_aside_by_the_queue(
    sessions: SessionFactory, queue: InMemoryTriggerQueue
) -> None:
    await enqueue(sessions, queue, "quanto custa o corte?", "Ana")
    down = worker(sessions, RecordingSender(failing=True))

    for _ in range(5):
        await process_next(down, queue, wait_seconds=0, pause=no_pause)

    assert await process_next(down, queue, wait_seconds=0, pause=no_pause) == 0
    assert [trigger.tenant_id for trigger in queue.set_aside] == [BARBERSHOP.id]


async def test_ing_6_a_turn_that_fails_every_attempt_goes_to_a_person(
    sessions: SessionFactory, queue: InMemoryTriggerQueue
) -> None:
    sender = RecordingSender()
    broken = worker(sessions, sender, BrokenProvider())
    receipt = await say(sessions, "quanto custa o corte?", "Ana-1", sender="Ana")
    await queue.send(
        Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id),
        deduplication_id="Ana-1",
    )

    for _ in range(5):
        await process_next(broken, queue, wait_seconds=0, pause=no_pause)

    conversation = await conversation_row(sessions, receipt.conversation_id)
    assert [message.text for message in sender.sent] == [HANDOFF_NOTICE]
    assert conversation["mode"] == "handoff"
    assert len(queue.set_aside) == 1
    assert await process_next(broken, queue, wait_seconds=0, pause=no_pause) == 0


async def test_ing_6_before_the_last_attempt_the_customer_hears_nothing(
    sessions: SessionFactory, queue: InMemoryTriggerQueue
) -> None:
    sender = RecordingSender()
    broken = worker(sessions, sender, BrokenProvider())
    await enqueue(sessions, queue, "quanto custa o corte?", "Ana")

    for _ in range(4):
        await process_next(broken, queue, wait_seconds=0, pause=no_pause)

    assert sender.sent == []
    assert queue.set_aside == []


async def test_ing_4_a_busy_conversation_stays_in_the_queue_without_counting_an_attempt(
    sessions: SessionFactory, queue: TriggerQueue
) -> None:
    await enqueue(sessions, queue, "quanto custa o corte?", "Ana")
    [waiting] = await waiting_triggers(queue)
    await queue.send(waiting, deduplication_id="again")
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        await open_turn(session, waiting.conversation_id, NOW)

    handled = await process_next(
        worker(sessions, RecordingSender()), queue, wait_seconds=0, pause=no_pause
    )
    lease = await queue.lease(wait_seconds=0)
    assert lease is not None
    delivery = await lease.receive()

    assert handled == 0
    assert delivery is not None
    assert delivery.attempt == 1


def test_a_failed_trigger_is_held_longer_at_each_attempt() -> None:
    assert [backoff_seconds(attempt) for attempt in range(1, 7)] == [2, 4, 8, 16, 30, 30]


async def test_the_loop_handles_conversations_side_by_side_and_stops_when_asked(
    sessions: SessionFactory, queue: TriggerQueue
) -> None:
    sender = RecordingSender()
    stop = asyncio.Event()
    running = asyncio.create_task(run(worker(sessions, sender), queue, stop, concurrency=2))

    await enqueue(sessions, queue, "quanto custa o corte?", "Ana")
    await enqueue(sessions, queue, "quanto custa a barba?", "Bruno")
    await asyncio.wait_for(sender.has_sent(2), timeout=10)
    stop.set()
    await asyncio.wait_for(running, timeout=2)

    assert sorted(message.recipient_external_id for message in sender.sent) == ["Ana", "Bruno"]


class AckFailsOnce(InMemoryTriggerQueue):
    """A queue whose first acknowledgement is lost, as when a session lock expires."""

    def __init__(self) -> None:
        super().__init__()
        self.failures_left = 1

    async def lease(self, *, wait_seconds: float) -> "InMemoryLease | None":
        lease = await super().lease(wait_seconds=wait_seconds)
        if lease is None:
            return None
        queue, acknowledge = self, lease.ack

        async def ack(delivery: Delivery) -> None:
            if queue.failures_left:
                queue.failures_left -= 1
                raise ConnectionError("the session lock was lost")
            await acknowledge(delivery)

        lease.ack = ack  # type: ignore[method-assign]
        return lease


async def test_a_lost_acknowledgement_does_not_stop_the_loop_or_repeat_the_reply(
    sessions: SessionFactory,
) -> None:
    queue, sender, stop = AckFailsOnce(), RecordingSender(), asyncio.Event()
    running = asyncio.create_task(run(worker(sessions, sender), queue, stop, concurrency=1))

    await enqueue(sessions, queue, "quanto custa o corte?", "Ana")
    await enqueue(sessions, queue, "quanto custa a barba?", "Bruno")
    await asyncio.wait_for(sender.has_sent(2), timeout=10)
    await asyncio.wait_for(queue.emptied(), timeout=10)
    stop.set()
    await asyncio.wait_for(running, timeout=2)

    assert sorted(message.recipient_external_id for message in sender.sent) == ["Ana", "Bruno"]


async def test_obs_2_logs_carry_ids_and_never_the_message_or_the_name(
    sessions: SessionFactory, queue: TriggerQueue, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    await enqueue(sessions, queue, SECRET_TEXT, "Mariana Albuquerque")

    await process_next(
        worker(sessions, RecordingSender(failing=True)), queue, wait_seconds=0, pause=no_pause
    )

    assert "turn_failed" in caplog.text
    assert "Mariana" not in caplog.text
    assert "quanto custa" not in caplog.text


async def test_obs_2_database_errors_do_not_quote_the_values_they_failed_on(
    sessions: SessionFactory,
) -> None:
    identity_of_nobody = text(
        """
        insert into customer_identities (tenant_id, channel, external_id, customer_id)
        values (:tenant, 'webchat', :name, :customer)
        """
    )

    with pytest.raises(IntegrityError) as failure:
        async with tenant_transaction(sessions, BARBERSHOP.id) as session:
            await session.execute(
                identity_of_nobody,
                {"tenant": BARBERSHOP.id, "name": "Mariana Albuquerque", "customer": uuid4()},
            )

    assert "Mariana" not in str(failure.value)
