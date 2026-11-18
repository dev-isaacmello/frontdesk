"""One trace per customer message, from the request that brings it to the reply (OBS-1).

The application emits OpenTelemetry and nothing of a vendor (ADR 0011). Spans carry ids,
names, counts and durations, and never what a customer wrote or is called. The names of
the model spans and their attributes follow the GenAI semantic conventions, which are
still in development and may be renamed.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_PROPAGATOR = TraceContextTextMapPropagator()
_HEADER = "traceparent"

# Held here and not installed as the global provider, which can be set once per process:
# a test gives the module an exporter of its own and takes it back.
_provider: trace.TracerProvider = trace.NoOpTracerProvider()


def configure(service: str, endpoint: str | None) -> None:
    """Sends spans to an OTLP endpoint over HTTP. With no endpoint, spans go nowhere."""
    if not endpoint:
        return
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    use(service, BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, timeout=5)))


def use(service: str, processor: SpanProcessor) -> TracerProvider:
    global _provider
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(processor)
    _provider = provider
    return provider


def exporting_to(exporter: SpanExporter) -> TracerProvider:
    """For tests: every span is handed to the exporter as soon as it ends."""
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    return use("frontdesk-test", SimpleSpanProcessor(exporter))


@contextmanager
def span(
    name: str,
    attributes: Mapping[str, Any] | None = None,
    *,
    parent: str | None = None,
    kind: SpanKind = SpanKind.INTERNAL,
) -> Iterator[Span]:
    """A span around a block. `parent` is a carried trace context, as `carried()` gives it.

    An exception that leaves the block marks the span as an error with the type of the
    exception and no message, since a message can quote what a customer wrote.
    """
    context = _PROPAGATOR.extract({_HEADER: parent}) if parent else None
    tracer = _provider.get_tracer("frontdesk")
    with tracer.start_as_current_span(
        name,
        context=context,
        kind=kind,
        attributes=dict(attributes or {}),
        record_exception=False,
        set_status_on_exception=False,
    ) as current:
        try:
            yield current
        except BaseException as error:
            current.set_attribute("error.type", type(error).__qualname__)
            current.set_status(Status(StatusCode.ERROR))
            raise


def carried() -> str | None:
    """The current trace context as one string, to travel in a message to another process."""
    carrier: dict[str, str] = {}
    _PROPAGATOR.inject(carrier)
    return carrier.get(_HEADER)
