"""OBS-1: one trace from the request that brings a message to the reply that answers it."""

import json
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from frontdesk import telemetry
from frontdesk.api.app import ApiDeps, create_app
from frontdesk.channels.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign
from frontdesk.channels.webchat import PostgresNotifications
from frontdesk.db.session import SessionFactory
from frontdesk.providers.scripted import calls, says
from frontdesk.queue.port import TriggerQueue
from frontdesk.seed import BARBERSHOP
from frontdesk.worker.handler import handle
from tests.conftest import Database
from tests.fakes import waiting_triggers
from tests.support import IN_SCOPE, RecordingSender, scripted_worker
from tests.tools.conftest import NOW

SECRET = "a-shared-secret-between-the-panel-and-the-api"
MESSAGES = f"/channels/webchat/{BARBERSHOP.slug}/messages"
SECRET_WORDS = "quanto custa o corte da Ana Souza?"


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    telemetry.exporting_to(exporter)
    yield exporter
    telemetry._provider = trace.NoOpTracerProvider()


@pytest.fixture
async def client(
    sessions: SessionFactory, queue: TriggerQueue, database: Database
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        ApiDeps(
            sessions=sessions,
            queue=queue,
            notifications=PostgresNotifications(database.app_dsn),
            webchat_secret=SECRET,
            clock=lambda: NOW,
            agent=scripted_worker(sessions, RecordingSender())[0].agent,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http:
        yield http


async def send(client: httpx.AsyncClient, text: str) -> None:
    body = json.dumps(
        {"session_id": "s1", "message_id": "m1", "text": text, "display_name": "Ana Souza"}
    ).encode()
    timestamp, signature = sign(SECRET, NOW, "POST", MESSAGES, body)
    response = await client.post(
        MESSAGES, content=body, headers={TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature}
    )
    assert response.status_code == 202


def named(spans: InMemorySpanExporter) -> dict[str, ReadableSpan]:
    return {span.name: span for span in spans.get_finished_spans()}


def parent_of(span: ReadableSpan, spans: InMemorySpanExporter) -> str | None:
    by_id = {each.context.span_id: each.name for each in spans.get_finished_spans()}
    return by_id.get(span.parent.span_id) if span.parent else None


async def a_turn(
    client: httpx.AsyncClient, sessions: SessionFactory, queue: TriggerQueue
) -> dict[str, Any]:
    """A price question, asked over HTTP and answered by the worker from the queue."""
    corte = BARBERSHOP.service_id("Corte")
    quote = calls("quote", {"service_ids": [str(corte)], "starts_at": "2026-11-18T14:00:00"})
    worker, _ = scripted_worker(
        sessions, RecordingSender(), IN_SCOPE, quote, says("O corte custa R$ 45,00.")
    )
    await send(client, SECRET_WORDS)
    [trigger] = await waiting_triggers(queue)
    await handle(worker, trigger)
    return {"trigger": trigger}


async def test_obs_1_one_trace_links_the_request_the_queue_the_worker_and_what_it_called(
    client: httpx.AsyncClient,
    sessions: SessionFactory,
    queue: TriggerQueue,
    spans: InMemorySpanExporter,
) -> None:
    await a_turn(client, sessions, queue)

    seen = named(spans)
    assert {span.context.trace_id for span in seen.values()} == {
        seen["receive webchat"].context.trace_id
    }
    assert {
        "receive webchat",
        "handle conversation",
        "node load_context",
        "node classify",
        "node plan",
        "node execute",
        "node validate",
        "chat scripted",
        "execute_tool quote",
        "send webchat",
    } <= set(seen)
    # The worker's span is a child of the request's, across the queue.
    assert parent_of(seen["handle conversation"], spans) == "receive webchat"
    assert parent_of(seen["execute_tool quote"], spans) == "node execute"
    assert parent_of(seen["chat scripted"], spans) in ("node classify", "node plan")


async def test_obs_1_a_model_call_is_a_span_with_its_model_and_its_tokens(
    client: httpx.AsyncClient,
    sessions: SessionFactory,
    queue: TriggerQueue,
    spans: InMemorySpanExporter,
) -> None:
    await a_turn(client, sessions, queue)

    call = dict(named(spans)["chat scripted"].attributes or {})
    assert call["gen_ai.operation.name"] == "chat"
    assert call["gen_ai.request.model"] == "scripted"
    assert (call["gen_ai.usage.input_tokens"], call["gen_ai.usage.output_tokens"]) == (100, 20)
    tool = dict(named(spans)["execute_tool quote"].attributes or {})
    assert (tool["gen_ai.operation.name"], tool["gen_ai.tool.name"]) == ("execute_tool", "quote")


async def test_obs_2_no_span_carries_what_the_customer_wrote_or_is_called(
    client: httpx.AsyncClient,
    sessions: SessionFactory,
    queue: TriggerQueue,
    spans: InMemorySpanExporter,
) -> None:
    await a_turn(client, sessions, queue)

    everything = json.dumps(
        [
            {"name": span.name, "attributes": dict(span.attributes or {})}
            for span in spans.get_finished_spans()
        ],
        default=str,
        ensure_ascii=False,
    )
    for private in (SECRET_WORDS, "Ana", "Souza", "45,00"):
        assert private not in everything


async def test_obs_1_a_tool_call_the_model_got_wrong_is_marked_on_its_span(
    client: httpx.AsyncClient,
    sessions: SessionFactory,
    queue: TriggerQueue,
    spans: InMemorySpanExporter,
) -> None:
    worker, _ = scripted_worker(
        sessions,
        RecordingSender(),
        IN_SCOPE,
        calls("quote", {"service_ids": ["not-an-id"]}),
        says("Qual serviço você quer?"),
    )
    await send(client, "quanto custa?")
    [trigger] = await waiting_triggers(queue)

    await handle(worker, trigger)

    assert dict(named(spans)["execute_tool quote"].attributes or {})["error.type"] == (
        "invalid_arguments"
    )


def test_obs_1_without_an_endpoint_spans_go_nowhere_and_nothing_fails() -> None:
    telemetry.configure("frontdesk-test", None)

    with telemetry.span("anything") as current:
        assert telemetry.carried() is None
        assert not current.is_recording()
