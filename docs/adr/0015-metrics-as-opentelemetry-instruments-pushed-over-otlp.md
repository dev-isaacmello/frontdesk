# 0015. Metrics are OpenTelemetry instruments, pushed over OTLP

Status: accepted

## Context

The traces of ADR 0011 answer what happened to one message. They do not answer how many, how often or how slow across all of them, which is what an alarm and a load test need. The specification lists what has to be countable: latency per node, tokens and cost per conversation and tenant, tool errors, guardrail blocks, handoffs, queue age and dead-letter size.

Most of this is already in PostgreSQL. Every model call is a row with its node, tokens, latency and cost, every turn has an outcome and every handoff a reason. That is where the panel reads from and it is exact. It is also behind row-level security, so the application can add up one tenant and never all of them, and a database that is down cannot report that it is down.

Checked on 2026-11-18, with the sources in docs/verificado.md: Prometheus receives OTLP over HTTP when started with a flag, and takes the service name as the job label. The managed OpenTelemetry agent of Azure Container Apps speaks gRPC only, and its Application Insights destination does not accept metrics. The GenAI metric conventions of OpenTelemetry are in development and their token metric is being replaced.

## Decision

The API and the worker record counters and histograms with the OpenTelemetry metrics API, in the places where the events happen, and push them over OTLP to an endpoint in configuration. With no endpoint nothing is recorded, which is the default.

The instruments are few. A histogram of how long each node of the graph took. For each model call, a histogram of its duration and counters of its tokens and of its cost in millionths of a dollar, recorded by the ledger after the row is committed. A counter of tool calls, with the error on the ones that failed. Counters of turns by outcome, of handoffs by reason, of drafts the checks blocked and of calls the provider's content filter refused. A histogram of how long the oldest message of a turn waited for the turn to start. Counters of trigger deliveries that failed and of triggers that were dead-lettered.

A point is labelled with a tenant id, a node, a model, a tool or an error type. It never carries a conversation, a customer or text, and a tool name the model made up is recorded as unknown. A test holds the labels to a fixed list.

Locally the destination is Prometheus, one more optional container beside Phoenix, started with a profile. It scrapes nothing.

The names are mine, under `frontdesk.`, and only the attributes that the spans already use keep their GenAI names.

## Alternatives rejected

Metrics only from the database. Exact and free, and it would be SQL views with no new code path. It fails the two cases above: one number across tenants, and a number while the database is the thing that is broken. I keep the database as the source for what the panel shows and for money.

A scrape endpoint in the Prometheus format. The worker has no HTTP server and would need one for this alone, and the application would be emitting a vendor's format next to OTLP.

Deriving metrics from spans in the backend. Phoenix does not do it, and it would make the numbers depend on which trace backend is running.

The GenAI metric names. I would follow a convention that is stable. This one is not, and a renamed metric breaks every alarm written on it.

A gauge of the oldest waiting message and of the size of the dead-letter queue, computed by the application. The first is a read across tenants, which the application's role cannot do and should not be given for this. The second is a state of Service Bus, which Service Bus already publishes.

## Cost of this choice

Cost per conversation is not a metric. A conversation as a label is one series per conversation, so the metrics have cost per tenant, node and model, and the cost of one conversation stays where it is exact: the ledger, the panel and the trace.

Queue age is measured when a turn starts. A queue nobody is consuming records nothing, so the alarm for a worker that is down has to be on the absence of turns, or on the platform's own count of active messages in the queue. The size of the dead-letter queue is likewise the platform's number; mine is a counter of what was sent there. The Terraform has an alert on the platform's count, and locally nothing watches it.

In Azure the application metrics are not wired. The managed agent wants gRPC where this exporter speaks HTTP, and the destination I would pick first does not take metrics. Pointing the endpoint at any OTLP destination over HTTP works without a code change, and I have only run it against the local Prometheus.

The metrics of the API and of the worker are separate series under two job names. A counter restarts from zero when its process does, which the rate functions of Prometheus handle and a raw read of the counter does not.

Tenant id as a label is one series per tenant for each combination of the others. With two tenants that is nothing. With thousands it is a cardinality to look at before turning this on.
