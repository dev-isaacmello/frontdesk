"""OBS-3: what a turn leaves behind as numbers, and what those numbers never carry."""

import json
import logging
from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, NumberDataPoint

from frontdesk import metrics
from frontdesk.db.session import SessionFactory
from frontdesk.providers.port import ModelFilteredError, ModelThrottledError
from frontdesk.providers.scripted import calls, says
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import BARBERSHOP
from frontdesk.worker.handler import WorkerDeps, handle
from frontdesk.worker.loop import process_next
from tests.fakes import InMemoryTriggerQueue
from tests.support import IN_SCOPE, RecordingSender, say, scripted_worker

SECRET_WORDS = "quanto custa o corte da Ana Souza?"
TENANT = str(BARBERSHOP.id)

LABELS = {
    "frontdesk.tenant_id",
    "frontdesk.node",
    "frontdesk.token.type",
    "frontdesk.turn.outcome",
    "frontdesk.handoff.reason",
    "gen_ai.request.model",
    "gen_ai.tool.name",
    "error.type",
}


@pytest.fixture
def measured() -> Iterator[InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    provider = metrics.use("frontdesk-test", reader)
    yield reader
    metrics.off()
    provider.shutdown()


def points(reader: InMemoryMetricReader, name: str) -> list[tuple[dict[str, Any], float]]:
    """Every series of a metric: its labels, and its sum or how many times it was recorded."""
    data = reader.get_metrics_data()
    return [
        (
            dict(point.attributes or {}),
            point.value if isinstance(point, NumberDataPoint) else point.count,
        )
        for resource in (data.resource_metrics if data else [])
        for scope in resource.scope_metrics
        for metric in scope.metrics
        if metric.name == name
        for point in metric.data.data_points
    ]


def total(reader: InMemoryMetricReader, name: str, **labels: str) -> float:
    wanted = {key.replace("__", "."): value for key, value in labels.items()}
    return sum(value for found, value in points(reader, name) if wanted.items() <= found.items())


def everything(reader: InMemoryMetricReader) -> list[dict[str, Any]]:
    data = reader.get_metrics_data()
    return [
        dict(point.attributes or {})
        for resource in (data.resource_metrics if data else [])
        for scope in resource.scope_metrics
        for metric in scope.metrics
        for point in metric.data.data_points
    ]


async def a_message(
    sessions: SessionFactory, text: str = SECRET_WORDS, sender: str = "Ana Souza"
) -> Trigger:
    receipt = await say(sessions, text, f"{sender}-1", sender=sender)
    return Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id)


def a_price_answer(sessions: SessionFactory) -> WorkerDeps:
    corte = BARBERSHOP.service_id("Corte")
    quote = calls("quote", {"service_ids": [str(corte)], "starts_at": "2026-11-18T14:00:00"})
    worker, _ = scripted_worker(
        sessions, RecordingSender(), IN_SCOPE, quote, says("O corte custa R$ 45,00.")
    )
    return worker


async def test_obs_3_a_turn_leaves_how_long_each_node_took(
    sessions: SessionFactory, measured: InMemoryMetricReader
) -> None:
    await handle(a_price_answer(sessions), await a_message(sessions))

    ran = {
        found["frontdesk.node"]: count
        for found, count in points(measured, "frontdesk.node.duration")
        if found["frontdesk.tenant_id"] == TENANT
    }
    assert ran == {
        "load_context": 1,
        "classify": 1,
        "retrieve": 1,
        "plan": 2,
        "gate": 1,
        "execute": 1,
        "validate": 1,
    }


async def test_obs_3_a_model_call_leaves_its_tokens_and_its_cost_under_the_tenant_and_the_node(
    sessions: SessionFactory, measured: InMemoryMetricReader
) -> None:
    await handle(a_price_answer(sessions), await a_message(sessions))

    # The scripted model spends 100 tokens in and 20 out per call, which the test price
    # table makes 140 micro-USD: once to classify, twice to plan.
    plan = {"frontdesk__tenant_id": TENANT, "frontdesk__node": "plan"}
    assert total(measured, "frontdesk.model.tokens", frontdesk__token__type="input", **plan) == 200
    assert total(measured, "frontdesk.model.tokens", frontdesk__token__type="output", **plan) == 40
    assert total(measured, "frontdesk.model.cost_microusd", **plan) == 280
    assert total(measured, "frontdesk.model.cost_microusd", frontdesk__tenant_id=TENANT) == 420
    assert total(measured, "frontdesk.model.duration", gen_ai__request__model="scripted") == 3


async def test_obs_3_a_turn_that_ends_is_counted_with_how_it_ended_and_how_long_it_waited(
    sessions: SessionFactory, measured: InMemoryMetricReader
) -> None:
    await handle(a_price_answer(sessions), await a_message(sessions))

    assert points(measured, "frontdesk.turns") == [
        ({"frontdesk.tenant_id": TENANT, "frontdesk.turn.outcome": "replied"}, 1)
    ]
    assert points(measured, "frontdesk.queue.wait") == [({"frontdesk.tenant_id": TENANT}, 1)]
    assert points(measured, "frontdesk.tool.calls") == [
        ({"frontdesk.tenant_id": TENANT, "gen_ai.tool.name": "quote"}, 1)
    ]
    assert points(measured, "frontdesk.handoffs") == []


async def test_obs_3_a_trigger_handled_twice_counts_its_turn_and_its_wait_once(
    sessions: SessionFactory, measured: InMemoryMetricReader
) -> None:
    worker, trigger = a_price_answer(sessions), await a_message(sessions)

    await handle(worker, trigger)
    await handle(worker, trigger)

    assert total(measured, "frontdesk.turns") == 1
    assert total(measured, "frontdesk.queue.wait") == 1


async def test_obs_3_blocked_drafts_and_the_handoff_they_end_in_are_counted(
    sessions: SessionFactory, measured: InMemoryMetricReader
) -> None:
    worker, _ = scripted_worker(
        sessions,
        RecordingSender(),
        IN_SCOPE,
        says("O corte sai por R$ 40,00."),
        says("Desculpe: R$ 42,00."),
    )

    await handle(worker, await a_message(sessions))

    assert total(measured, "frontdesk.guardrail.blocks", frontdesk__tenant_id=TENANT) == 2
    assert points(measured, "frontdesk.handoffs") == [
        ({"frontdesk.tenant_id": TENANT, "frontdesk.handoff.reason": "guardrail_blocked"}, 1)
    ]
    assert total(measured, "frontdesk.turns", frontdesk__turn__outcome="handoff") == 1


async def test_obs_3_a_tool_call_the_model_got_wrong_is_counted_as_an_error_of_that_tool(
    sessions: SessionFactory, measured: InMemoryMetricReader
) -> None:
    worker, _ = scripted_worker(
        sessions,
        RecordingSender(),
        IN_SCOPE,
        calls("quote", {"service_ids": ["not-an-id"]}),
        says("Qual serviço você quer?"),
    )

    await handle(worker, await a_message(sessions, "quanto custa?"))

    assert (
        total(
            measured,
            "frontdesk.tool.calls",
            gen_ai__tool__name="quote",
            error__type="invalid_arguments",
        )
        == 1
    )


async def test_obs_3_a_tool_name_the_model_made_up_does_not_become_a_label(
    sessions: SessionFactory, measured: InMemoryMetricReader
) -> None:
    worker, _ = scripted_worker(
        sessions,
        RecordingSender(),
        IN_SCOPE,
        calls("apagar_tudo_da_Ana_Souza", {}),
        says("Não consigo fazer isso."),
    )

    await handle(worker, await a_message(sessions, "apaga tudo"))

    assert points(measured, "frontdesk.tool.calls") == [
        (
            {
                "frontdesk.tenant_id": TENANT,
                "gen_ai.tool.name": "unknown",
                "error.type": "unknown_tool",
            },
            1,
        )
    ]


async def test_obs_3_a_message_the_provider_filter_refused_is_counted_and_logged_with_its_turn(
    sessions: SessionFactory, measured: InMemoryMetricReader, caplog: pytest.LogCaptureFixture
) -> None:
    worker, _ = scripted_worker(sessions, RecordingSender(), ModelFilteredError("content_filter"))
    trigger = await a_message(sessions)

    with caplog.at_level(logging.WARNING, logger="frontdesk.agent.graph"):
        await handle(worker, trigger)

    assert points(measured, "frontdesk.model.filtered") == [
        ({"frontdesk.tenant_id": TENANT, "frontdesk.node": "classify"}, 1)
    ]
    assert total(measured, "frontdesk.turns", frontdesk__turn__outcome="refused") == 1
    [line] = [record for record in caplog.records if record.getMessage() == "model_filtered"]
    assert (line.node, line.conversation_id) == ("classify", str(trigger.conversation_id))  # type: ignore[attr-defined]


async def test_obs_3_a_model_call_the_provider_throttled_is_counted_where_it_waited(
    sessions: SessionFactory, measured: InMemoryMetricReader
) -> None:
    worker, _ = scripted_worker(
        sessions,
        RecordingSender(),
        ModelThrottledError("slow down", retry_after=0.001),
        IN_SCOPE,
        says("Temos corte e barba."),
    )

    await handle(worker, await a_message(sessions, "quais serviços vocês têm?"))

    assert points(measured, "frontdesk.model.throttled") == [
        (
            {
                "frontdesk.tenant_id": TENANT,
                "frontdesk.node": "classify",
                "gen_ai.request.model": "scripted",
            },
            1,
        )
    ]
    assert total(measured, "frontdesk.turns", frontdesk__turn__outcome="replied") == 1


async def test_obs_3_a_trigger_that_never_succeeds_counts_each_failure_and_one_dead_letter(
    sessions: SessionFactory, queue: InMemoryTriggerQueue, measured: InMemoryMetricReader
) -> None:
    worker, _ = scripted_worker(sessions, RecordingSender(), *[TimeoutError("down")] * 5)
    trigger = await a_message(sessions)
    await queue.send(trigger, deduplication_id="m1")

    for _ in range(5):
        await process_next(worker, queue, wait_seconds=0, pause=lambda _attempt: 0)

    assert len(queue.set_aside) == 1
    assert points(measured, "frontdesk.trigger.failures") == [({"error.type": "TimeoutError"}, 5)]
    assert total(measured, "frontdesk.trigger.dead_lettered") == 1
    assert points(measured, "frontdesk.handoffs") == [
        ({"frontdesk.tenant_id": TENANT, "frontdesk.handoff.reason": "agent_failed"}, 1)
    ]
    assert total(measured, "frontdesk.turns", frontdesk__turn__outcome="failed") == 1


async def test_obs_2_no_metric_carries_what_the_customer_wrote_or_is_called(
    sessions: SessionFactory, measured: InMemoryMetricReader
) -> None:
    trigger = await a_message(sessions)
    await handle(a_price_answer(sessions), trigger)
    # A turn that ends in every other way a label can come from: a made-up tool, drafts
    # that are blocked and the handoff after them.
    made_up, _ = scripted_worker(
        sessions,
        RecordingSender(),
        IN_SCOPE,
        calls("apagar_tudo_da_Ana_Souza", {}),
        says("O corte sai por R$ 40,00."),
        says("Desculpe: R$ 42,00."),
    )
    await handle(made_up, await a_message(sessions, sender="Bruno Lima"))

    labels = everything(measured)
    assert {key for found in labels for key in found} == LABELS
    said = json.dumps(labels, ensure_ascii=False)
    for private in (SECRET_WORDS, "Ana", "Souza", "Bruno", "45,00", str(trigger.conversation_id)):
        assert private not in said


def test_obs_3_without_an_endpoint_nothing_is_kept_and_nothing_fails() -> None:
    metrics.configure("frontdesk-test", None)

    metrics.node_ran(BARBERSHOP.id, "plan", 0.2)
    metrics.trigger_dead_lettered()
