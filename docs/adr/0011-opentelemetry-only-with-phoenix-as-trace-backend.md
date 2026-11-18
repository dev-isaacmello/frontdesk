# 0011. Emit OpenTelemetry only; Phoenix as the default trace backend

Status: accepted

## Context

One trace has to connect webhook, queue, worker, graph nodes, model calls and tools. I also want to look at prompts and tool calls per turn while developing and evaluating. The options today, checked in docs/verificado.md:

- Langfuse. MIT core. Self-hosting the current version needs PostgreSQL, ClickHouse, Redis and blob storage plus two application containers; the compose guide asks for at least 4 cores and 16 GiB. Cloud has a free tier of 50k units per month with 30 days of retention, then USD 29 per month.
- LangSmith. Free tier of 5k traces per month with 14 days of retention, then USD 39 per seat. Self-hosting is an Enterprise add-on.
- Arize Phoenix. One container, SQLite by default or PostgreSQL, Elastic License 2.0, free to self-host with no feature limits. The managed product is Arize AX, with a free tier of 25k spans per month.

All three accept OTLP. The OpenTelemetry GenAI semantic conventions are still in Development status, and the official GenAI instrumentation packages are beta.

## Decision

The application emits OpenTelemetry and nothing vendor specific. Spans for model calls and tool calls are created by hand in the two places that wrap them, using the GenAI attribute names as they are today. Trace context travels in the queue message attributes so the worker continues the trace the webhook started.

The default backend is Phoenix, self-hosted: one extra container in the compose file, storing in the same PostgreSQL. A reviewer who runs the project locally can open the trace of the message they just sent without creating an account anywhere.

The backend is an OTLP endpoint in configuration. Pointing it at Langfuse Cloud or LangSmith is a change of environment variables.

Message content is not attached to spans by default. A flag turns it on for local development and for the eval runs.

## Alternatives rejected

Langfuse self-hosted. The best fit in features, but four stateful services for a demo is more infrastructure than the product it observes.

A managed backend as the default. Zero operations, but the first run would need an account and a key, and traces of the public demo would sit in a third party by default.

LangSmith as the default. I use it in production elsewhere and it works; here the free retention is short, self-hosting is not available, and its OTLP endpoint drops spans whose parent was not sent to it, which is a risk for a trace that starts in the webhook.

Auto-instrumentation packages for LangChain or for the model SDK. Beta, tied to conventions that are still changing, and I would not control which attributes carry customer text.

## Cost of this choice

Phoenix is under the Elastic License, not an OSI license; that is fine for self-hosting and worth knowing. In Azure it is a fourth container app and more rows in the database, so it is optional there and off by default in the cost estimate. Azure Monitor now ingests OTLP as well, through a collector with Entra authentication, which makes it a second backend to point the same spans at without changing the application. Because the GenAI conventions are not stable, attribute names may need a rename later. Hand-written spans mean a model call I forget to wrap is invisible, so the provider port is the only place allowed to call a provider.

## As built

The spans are written by hand in five places: the inbound request, the worker, the wrapper every graph node runs in, the one function through which a node calls a model, and the tool runner. The trace context travels in the trigger. Phoenix is in the compose file under a profile of its own and keeps its data in a volume, not in the application's PostgreSQL as planned above: one less thing sharing the database, and nothing to create in it. On 2026-11-18 one message sent through the web chat to a real model arrived there as one trace of 21 spans, from the request to the send, with the worker's span a child of the request's across the queue.
