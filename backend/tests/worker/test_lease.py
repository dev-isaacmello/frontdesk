"""ING-4 and ING-5: one worker per conversation, and a burst of messages as one turn."""

from dataclasses import replace
from datetime import datetime, timedelta
from uuid import UUID

import pytest

from frontdesk.agent.turn import TurnInput, TurnResult
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.conversations import (
    ConversationBusyError,
    StaleLeaseError,
    close_turn,
    open_turn,
    transcript,
)
from frontdesk.providers.port import ModelRequest, ModelResponse
from frontdesk.providers.scripted import says
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import BARBERSHOP
from frontdesk.worker.handler import handle
from tests.support import IN_SCOPE, RecordingSender, say, scripted_worker
from tests.tools.conftest import NOW

LATER = NOW + timedelta(minutes=10)


async def opened(
    sessions: SessionFactory, conversation_id: UUID, now: datetime
) -> TurnInput | None:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        return await open_turn(session, conversation_id, now)


async def test_ing_4_a_conversation_being_handled_is_not_taken_by_a_second_worker(
    sessions: SessionFactory,
) -> None:
    receipt = await say(sessions, "oi", "m1")
    first = await opened(sessions, receipt.conversation_id, NOW)

    with pytest.raises(ConversationBusyError):
        await opened(sessions, receipt.conversation_id, NOW + timedelta(seconds=30))

    assert first is not None


async def test_ing_4_a_worker_that_lost_its_lease_cannot_commit(sessions: SessionFactory) -> None:
    receipt = await say(sessions, "oi", "m1")
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        slow = await open_turn(session, receipt.conversation_id, NOW)
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        taker = await open_turn(session, receipt.conversation_id, LATER)
    assert slow is not None
    assert taker is not None

    with pytest.raises(StaleLeaseError):
        async with tenant_transaction(sessions, BARBERSHOP.id) as session:
            await close_turn(
                session, receipt.conversation_id, slow, TurnResult("replied", "tarde demais"), LATER
            )
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        await close_turn(
            session, receipt.conversation_id, taker, TurnResult("replied", "Oi, Ana!"), LATER
        )
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        said = await transcript(session, receipt.conversation_id)

    assert taker.turn_id == slow.turn_id
    assert [(line.author, line.text) for line in said] == [
        ("customer", "oi"),
        ("agent", "Oi, Ana!"),
    ]


async def test_ing_4_a_turn_that_failed_frees_the_conversation_for_its_retry(
    sessions: SessionFactory,
) -> None:
    class Broken:
        name = "broken"

        async def complete(self, _request: ModelRequest) -> ModelResponse:
            raise TimeoutError("model provider is down")

    sender = RecordingSender()
    healthy, _ = scripted_worker(sessions, sender)
    failing = replace(healthy, agent=replace(healthy.agent, provider=Broken()))
    working, _ = scripted_worker(sessions, sender, IN_SCOPE, says("Oi, Ana!"))
    receipt = await say(sessions, "oi", "m1")
    trigger = Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id)

    with pytest.raises(TimeoutError):
        await handle(failing, trigger)
    await handle(working, trigger)

    assert [message.text for message in sender.sent] == ["Oi, Ana!"]


async def test_ing_5_a_message_that_arrives_during_the_quiet_window_joins_the_turn(
    sessions: SessionFactory,
) -> None:
    sender = RecordingSender()
    deps, provider = scripted_worker(sessions, sender, IN_SCOPE, says("Temos corte e barba."))
    clock = [NOW]
    waits: list[float] = []

    async def burst(seconds: float) -> None:
        """The customer sends a second message one second into the first wait."""
        waits.append(seconds)
        if len(waits) == 1:
            arrived = NOW + timedelta(seconds=1)
            await say(sessions, "quais serviços vocês têm?", "m2", sent_at=arrived)
        clock[0] += timedelta(seconds=seconds)

    deps = replace(deps, clock=lambda: clock[0], quiet_window=timedelta(seconds=2), sleep=burst)
    receipt = await say(sessions, "oi", "m1")

    await handle(deps, Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id))

    # Two seconds for the first message, then one more: the second arrived a second later.
    assert waits == [2.0, 1.0]
    assert provider.requests[-1].messages[-1].content == "oi\nquais serviços vocês têm?"
    assert len(sender.sent) == 1


async def test_ing_5_with_no_quiet_window_the_turn_starts_at_once(sessions: SessionFactory) -> None:
    sender = RecordingSender()
    deps, _ = scripted_worker(sessions, sender, IN_SCOPE, says("Oi, Ana!"))
    slept: list[float] = []

    async def record(seconds: float) -> None:
        slept.append(seconds)

    deps = replace(deps, sleep=record)
    receipt = await say(sessions, "oi", "m1")

    await handle(deps, Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id))

    assert slept == []
    assert len(sender.sent) == 1
