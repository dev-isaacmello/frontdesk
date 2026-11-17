"""The outbound half of the web chat: a reply reaches the stream of its conversation."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from frontdesk.agent.graph import AgentDeps
from frontdesk.channels.webchat import (
    PostgresNotifications,
    ServerEvent,
    WebchatSender,
    conversation_events,
)
from frontdesk.db.session import SessionFactory
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.port import ModelResponse
from frontdesk.providers.scripted import ScriptedProvider, says
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import BARBERSHOP
from frontdesk.worker.handler import WorkerDeps, handle
from tests.conftest import Database
from tests.support import IN_SCOPE, PRICES, say
from tests.tools.conftest import NOW


@pytest.fixture
async def notifications(database: Database) -> AsyncIterator[PostgresNotifications]:
    listener = PostgresNotifications(database.app_dsn)
    await listener.start()
    yield listener
    await listener.stop()


def worker(sessions: SessionFactory, *script: ModelResponse) -> WorkerDeps:
    agent = AgentDeps(
        sessions=sessions,
        provider=ScriptedProvider(script),
        model="scripted",
        ledger=ModelLedger(sessions, PRICES),
    )
    return WorkerDeps(
        sessions=sessions,
        agent=agent,
        senders={"webchat": WebchatSender(sessions)},
        clock=lambda: NOW,
    )


async def next_message(stream: AsyncIterator[ServerEvent]) -> ServerEvent:
    async with asyncio.timeout(5):
        async for event in stream:
            if event.event == "message":
                return event
    raise AssertionError("the stream ended without a message")


async def test_pan_1_a_reply_reaches_a_stream_that_was_already_open(
    sessions: SessionFactory, notifications: PostgresNotifications
) -> None:
    receipt = await say(sessions, "oi", "m1")
    stream = conversation_events(
        sessions, notifications, BARBERSHOP.id, receipt.conversation_id, after=None
    )
    waiting = asyncio.create_task(next_message(stream))
    await asyncio.sleep(0.1)  # let the stream subscribe before the reply exists

    await handle(
        worker(sessions, IN_SCOPE, says("Oi! Como posso ajudar?")),
        Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id),
    )
    event = await waiting

    assert event.data == {"author": "agent", "text": "Oi! Como posso ajudar?"}


async def test_pan_1_a_stream_opened_late_replays_what_it_missed_and_resumes_after_a_cursor(
    sessions: SessionFactory, notifications: PostgresNotifications
) -> None:
    deps = worker(sessions, IN_SCOPE, says("Primeira."), IN_SCOPE, says("Segunda."))
    for message_id, text in (("m1", "oi"), ("m2", "e aí")):
        receipt = await say(sessions, text, message_id)
        await handle(
            deps, Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id)
        )

    def open_stream(after: str | None) -> AsyncIterator[ServerEvent]:
        return conversation_events(
            sessions, notifications, BARBERSHOP.id, receipt.conversation_id, after=after
        )

    from_the_start = open_stream(None)
    first = await next_message(from_the_start)
    second = await next_message(from_the_start)
    resumed = await next_message(open_stream(first.id))

    assert [first.data["text"], second.data["text"]] == ["Primeira.", "Segunda."]
    assert resumed.data["text"] == "Segunda."
