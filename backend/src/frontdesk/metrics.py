"""Counts and durations of what the system does, for a graph or an alarm (OBS-3).

OpenTelemetry instruments, pushed over OTLP to an endpoint in configuration, like the
spans (ADR 0015). The names are this application's: the GenAI metric conventions are
being rewritten, and I would rather own a name than follow one that is about to change.

A point carries a tenant id, a node, a model or a tool name and nothing else. Never a
conversation, a customer or text: those are in the trace and the database, and as labels
they would make one series per conversation.
"""

from collections.abc import Sequence
from uuid import UUID

from opentelemetry import metrics as otel
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import MetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource

EXPORT_INTERVAL_MS = 15_000

# From ten milliseconds to over a minute, doubling: a database read and a slow model
# call both land in a bucket of their own.
_SECONDS: Sequence[float] = tuple(0.01 * 2**step for step in range(14))

_TENANT = "frontdesk.tenant_id"
_NODE = "frontdesk.node"
_MODEL = "gen_ai.request.model"


class _Instruments:
    def __init__(self, meter: otel.Meter) -> None:
        self.node_duration = meter.create_histogram(
            "frontdesk.node.duration",
            unit="s",
            description="How long one node of the graph took.",
            explicit_bucket_boundaries_advisory=_SECONDS,
        )
        self.model_duration = meter.create_histogram(
            "frontdesk.model.duration",
            unit="s",
            description="How long one call to a model took, as the provider adapter timed it.",
            explicit_bucket_boundaries_advisory=_SECONDS,
        )
        self.model_tokens = meter.create_counter(
            "frontdesk.model.tokens", unit="{token}", description="Tokens of model calls."
        )
        self.model_cost = meter.create_counter(
            "frontdesk.model.cost_microusd",
            description="What model calls cost, in millionths of a US dollar.",
        )
        self.model_filtered = meter.create_counter(
            "frontdesk.model.filtered",
            description="Model calls the provider's content filter refused.",
        )
        self.model_throttled = meter.create_counter(
            "frontdesk.model.throttled",
            description="Model calls the provider refused for being over its rate.",
        )
        self.tool_calls = meter.create_counter(
            "frontdesk.tool.calls",
            description="Tool calls a model asked for. error.type is set on the ones that failed.",
        )
        self.turns = meter.create_counter(
            "frontdesk.turns", description="Turns that ended, by how they ended."
        )
        self.handoffs = meter.create_counter(
            "frontdesk.handoffs", description="Conversations handed to a person, by reason."
        )
        self.guardrail_blocks = meter.create_counter(
            "frontdesk.guardrail.blocks", description="Drafts of a reply the checks refused."
        )
        self.queue_wait = meter.create_histogram(
            "frontdesk.queue.wait",
            unit="s",
            description="How long the oldest message of a turn waited for the turn to start.",
            explicit_bucket_boundaries_advisory=_SECONDS,
        )
        self.trigger_failures = meter.create_counter(
            "frontdesk.trigger.failures",
            description="Deliveries of a trigger that ended in an error and were given back.",
        )
        self.dead_letters = meter.create_counter(
            "frontdesk.trigger.dead_lettered",
            description="Triggers that failed their last delivery and were dead-lettered.",
        )


def _nowhere() -> _Instruments:
    return _Instruments(otel.NoOpMeterProvider().get_meter("frontdesk"))


# Held here and not installed as the global provider, for the reason telemetry.py gives.
_instruments = _nowhere()


def configure(service: str, endpoint: str | None) -> None:
    """Pushes the metrics to an OTLP endpoint over HTTP. With no endpoint, nothing is kept."""
    if not endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

    use(
        service,
        PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint, timeout=5),
            export_interval_millis=EXPORT_INTERVAL_MS,
        ),
    )


def use(service: str, reader: MetricReader) -> MeterProvider:
    global _instruments
    provider = MeterProvider(
        metric_readers=[reader], resource=Resource.create({"service.name": service})
    )
    _instruments = _Instruments(provider.get_meter("frontdesk"))
    return provider


def off() -> None:
    """Back to recording nothing, which is how a process without an endpoint runs."""
    global _instruments
    _instruments = _nowhere()


def node_ran(tenant_id: UUID, node: str, seconds: float) -> None:
    _instruments.node_duration.record(seconds, {_TENANT: str(tenant_id), _NODE: node})


def model_called(
    tenant_id: UUID,
    *,
    node: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_microusd: int,
    seconds: float,
) -> None:
    called = {_TENANT: str(tenant_id), _NODE: node, _MODEL: model}
    _instruments.model_duration.record(seconds, called)
    _instruments.model_tokens.add(input_tokens, {**called, "frontdesk.token.type": "input"})
    _instruments.model_tokens.add(output_tokens, {**called, "frontdesk.token.type": "output"})
    _instruments.model_cost.add(cost_microusd, called)


def model_filtered(tenant_id: UUID, node: str) -> None:
    _instruments.model_filtered.add(1, {_TENANT: str(tenant_id), _NODE: node})


def model_throttled(tenant_id: UUID, node: str, model: str) -> None:
    _instruments.model_throttled.add(1, {_TENANT: str(tenant_id), _NODE: node, _MODEL: model})


def tool_called(tenant_id: UUID, tool: str, error: str | None) -> None:
    called = {_TENANT: str(tenant_id), "gen_ai.tool.name": tool}
    _instruments.tool_calls.add(1, {**called, "error.type": error} if error else called)


def draft_blocked(tenant_id: UUID) -> None:
    _instruments.guardrail_blocks.add(1, {_TENANT: str(tenant_id)})


def turn_ended(tenant_id: UUID, outcome: str, handoff_reason: str | None = None) -> None:
    _instruments.turns.add(1, {_TENANT: str(tenant_id), "frontdesk.turn.outcome": outcome})
    if handoff_reason:
        _instruments.handoffs.add(
            1, {_TENANT: str(tenant_id), "frontdesk.handoff.reason": handoff_reason}
        )


def waited(tenant_id: UUID, seconds: float) -> None:
    _instruments.queue_wait.record(max(seconds, 0.0), {_TENANT: str(tenant_id)})


def trigger_failed(error: BaseException) -> None:
    _instruments.trigger_failures.add(1, {"error.type": type(error).__qualname__})


def trigger_dead_lettered() -> None:
    _instruments.dead_letters.add(1)
