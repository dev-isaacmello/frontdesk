# Specification

Status: accepted on 2026-11-17 as the working contract for Phases 1 to 6. A requirement changes here first and in the code second. Test names cite the requirement id they prove.

## Product

A small business answers the same questions and books the same slots all day on WhatsApp. This system answers and books for it, inside the limits the business sets, and hands the conversation to a person when it should not decide alone. Two fictional tenants ship in the seed: a barbershop and a sports arena.

## Constraints

- The project may cost at most USD 5 in real money. It runs on an Azure for Students subscription with credit and no payment method, so nothing on Azure can reach a card. Model tokens for development and evaluation stay under USD 5 of that credit, and the eval runner refuses a run whose estimate passes what is left.
- There is no permanent public demo. The README links a short video. The Azure deployment is applied for a measured window, its numbers are recorded in docs/medicoes.md, and it is destroyed.
- No paid resource is created and no `terraform apply` runs without the owner approving that command.
- No secret in the repository. No long-lived cloud credential anywhere.
- One command starts everything locally with no cloud account, using a deterministic fake model.
- Code, commits, ADRs and README in English. Agent prompts, golden set and seed in pt-BR.

## Requirements

Each line is one behavior that a test can prove. The number in brackets is the phase that delivers it.

Ingestion and reliability

- ING-1 [1] An inbound request is authenticated over its raw body before anything is parsed or stored.
- ING-2 [1] An inbound message is stored once per provider message id. A redelivery is acknowledged with 2xx and causes no second reply and no second booking.
- ING-3 [1] The endpoint returns after storing the event and sending the queue trigger. It never calls a model.
- ING-4 [2] Two turns of the same conversation never run at the same time, including when a worker loses its lock on the queue in the middle of a turn. Turns of different conversations run in parallel. Phase 1 has the queue's part of it: one conversation is leased to one worker at a time.
- ING-5 [2] Messages that arrive from one customer within the quiet window become one turn.
- ING-6 [2] A turn that keeps failing is retried with growing delay, then moved to the dead-letter queue, and the conversation is handed to a person. Phase 1 has the retry with growing delay and the dead-letter queue; the handoff is Phase 2.
- ING-7 [1] The graph receives and returns channel-neutral messages. Web chat and WhatsApp go through the same worker code.
- ING-8 [5] The WhatsApp adapter verifies the webhook signature, routes by phone number id, identifies the customer by business-scoped user id, and paces sends to one message every 6 seconds per customer.

Scheduling

- BOOK-1 [1] A price is always quoted for a service at a specific time, from the tenant's price windows.
- BOOK-2 [1] Availability returns only slots inside business hours, free of bookings and blocks, long enough for the service.
- BOOK-3 [1] Two confirmed bookings on the same resource cannot overlap. The database enforces it under concurrent attempts.
- BOOK-4 [1] A retried write with the same idempotency key returns the first result and creates nothing.
- BOOK-5 [1] A customer can list, reschedule and cancel only their own bookings.
- BOOK-6 [1] All times are stored in UTC and interpreted in the tenant's timezone.

Agent

- AGT-1 [1] The turn runs as an explicit graph. Phase 1 has load context, classify, refuse, plan and execute, and the planner's last message is the reply. Gate, validate and the regenerating compose join in Phase 2, retrieve in Phase 4.
- AGT-2 [1] Every write goes through a tool whose arguments passed schema validation. Tenant and customer come from the worker context, never from model output.
- AGT-3 [2] A turn stops at fixed limits of tool rounds, model calls and tokens, and ends in handoff instead of an error.
- AGT-4 [1] A message outside the tenant's business gets the fixed refusal and no further model call.
- AGT-5 [1] A turn produces one outbound message, plus a wait notice when it pauses for approval.

Policy and owner rules

- POL-1 [2] A reply never states a discount that is not registered, whatever the owner rules or the customer say.
- POL-2 [2] An owner rule saved in the panel is in force on the next turn.
- POL-3 [2] An owner rule that contradicts the hard policy has no effect and is listed as a finding.
- POL-4 [2] Instructions inside a customer message do not change tools, tenant, customer or policy.

Numeric guardrail

- GRD-1 [2] Every money amount, time, date, duration and count in a reply is extracted, including pt-BR written forms and relative dates.
- GRD-2 [2] A price, availability or booking time passes only if a tool result of the same turn contains the same typed value.
- GRD-3 [2] A value that cannot be typed, or has no allowed origin, blocks the reply.
- GRD-4 [2] The first block regenerates the reply once with the offending value named. The second ends in handoff.
- GRD-5 [2] The module imports nothing from the rest of the project.
- GRD-6 [2] A reply that claims a booking, a change or a cancellation is sent only if a tool of the same turn did it.

Approval and handoff

- APR-1 [2] An action the tenant marks as sensitive pauses the turn, appears in the owner's queue, and tells the customer to wait.
- APR-2 [2] The owner's decision resumes that turn. An approved action is validated again before it is written.
- APR-3 [2] While an approval is pending, new customer messages are answered in new turns.
- HND-1 [2] The conversation goes to a person when the customer asks, when a turn fails through all its retries, when a turn reaches one of its limits, when the guardrail blocks twice, and when the budget is exhausted. In handoff the agent stays silent.

Multi-tenancy and knowledge

- TEN-1 [1] With no tenant set, the runtime database role reads and writes nothing in any tenant table.
- TEN-2 [1] With tenant A set, the runtime role cannot read or write tenant B's rows, including with an explicit filter on B.
- TEN-3 [1] A tenant set in one transaction is not visible in the next transaction on the same pooled connection.
- KB-1 [4] Retrieval for tenant A never returns a chunk of tenant B, with the application trying to.
- KB-2 [4] A labelled retrieval set reports recall and precision at k.

Cost

- CST-1 [1] Every model call is recorded with tokens, latency and cost computed from a versioned price table.
- CST-2 [4] The router picks the model by graph node and tenant plan.
- CST-3 [4] A tenant over its monthly budget is served by the smaller model, then only by handoff.
- CST-4 [4] Every outbound message records its channel cost.
- CST-5 [4] A deployment-wide daily cap stops model calls when reached and can be switched by hand.

Evaluation

- EVAL-1 [3] A versioned pt-BR golden set covers tool choice, arguments, numeric fidelity, policy, refusal, prompt injection and approval.
- EVAL-2 [3] Evaluators are deterministic where the property allows it. A model judge has a versioned rubric.
- EVAL-3 [3] A pull request that touches prompts, graph, tools or router fails when a metric drops past its threshold against the baseline of main, and the report is posted on it.
- EVAL-4 [3] The same suite runs against every model the subscription can deploy that accepts tool calling, and outputs quality, latency and cost per conversation side by side. A model left out is listed with the reason.
- EVAL-6 [3] The owner's panel shows that comparison, and the default model is the one the numbers support.
- EVAL-5 [3] A run refuses to start when its estimated cost passes the remaining budget.

Observability and operation

- OBS-1 [6] One trace links webhook, queue, worker, graph nodes, model calls and tools.
- OBS-2 [1] Logs are structured and never contain a phone number, a name or a message body.
- OBS-3 [6] Metrics exist for latency per node, tokens and cost per conversation and tenant, tool errors, guardrail blocks, handoffs, queue age and dead-letter size.
- OPS-1 [6] A reproducible load script and a scripted chaos scenario publish their results.
- OPS-2 [6] Runbooks exist for queue growing, model provider down, webhook signature failing and cost over budget.

Panel

- PAN-1 [1] A web chat sends messages through the same pipeline and shows status and the final reply.
- PAN-2 [2] The owner sees conversations with the step timeline of each reply, the approval queue and the rules editor with findings.
- PAN-3 [4] The owner sees cost and quality by period.
- PAN-4 [1] No token or key reaches the browser. The browser talks only to the Next.js server.
- PAN-5 [1] Mobile and desktop are separate layouts, and empty, loading and error states are designed.

Infrastructure

- INF-1 [5] Terraform with remote state creates the environment on Azure: three container apps and a setup job on Container Apps, PostgreSQL flexible server, a Service Bus session queue with its dead-letter queue, Key Vault, a container registry and a log workspace.
- INF-2 [5] GitHub Actions deploys through OIDC with a federated identity. Each workload has a managed identity that holds only the roles it uses, and no service is reached with an access key where the service accepts an identity.
- INF-3 [5] `terraform destroy` leaves nothing billed.

## How it is built

Test first. One failing test for one behavior, the smallest code that passes it, then the next. Tests are written at these seams and nowhere else:

- Tools. `tool.run(context, arguments, session)` against a real PostgreSQL. Catches schedule, price and booking rules and the database constraints. Does not catch model behavior.
- Tenant isolation. SQL as the runtime role against a real PostgreSQL. Catches leaks across tenants. Does not catch authorization inside a tenant.
- HTTP. The FastAPI application called in process. Catches authentication, idempotency and the response contract.
- Worker. `handle(trigger)` and the loop with the offline model, a real PostgreSQL and the in-memory queue. Catches grouping, retries and the outbox.
- Queue. One contract suite run against the in-memory queue and against Service Bus in Microsoft's emulator. Catches ordering, exclusivity, deduplication and redelivery, and keeps the in-memory queue honest.
- Graph. One turn with a scripted fake model. Catches routing between nodes and limits.
- Pure modules. Guardrail, policy gate and cost, as functions.
- Provider adapters. Translation to and from provider payloads in the documented format, over a canned HTTP transport. This is the only place with mocks.
- End to end. The compose stack driven by a script, for the latency measurement and the smoke test.

Expected values in tests are literals worked out by hand from the seed, never recomputed with the code under test.

Quality gates, the same locally and in CI: `ruff format --check`, `ruff check`, `mypy --strict`, `pytest`, and for the panel lint, typecheck and build.

## Layout

```
backend/            Python package, migrations, tests
  src/frontdesk/
    domain/         catalog, schedule, bookings
    db/             engine, session, tenant context
    tools/          tool objects over the domain
    agent/          graph, nodes, state
    providers/      model port and adapters
    channels/       channel port and adapters
    queue/          queue port and the Service Bus client
    api/            FastAPI application
    worker/         queue consumer
web/                Next.js panel and chat
evals/              golden set, evaluators, runner
infra/              Terraform
docs/               this file, ADRs, measurements, runbooks
compose.yaml
```

## Phases

Each phase ends with its tests passing, an entry in docs/medicoes.md with a measured number and the command that reproduces it, and a tag.

1. Vertical slice, local. Web chat, queue, worker, graph with scheduling tools, PostgreSQL, seed, compose. Number: latency from message accepted to reply delivered.
2. Reliability. Guardrail, policy and owner rules, approval, handoff, ordering. Number: block rate on adversarial cases with the false block rate on benign cases.
3. Evaluation. Golden set, evaluators, CI gate, model comparison. Number: metrics before and after one real prompt change, and the comparison table.
4. Multi-tenancy and cost. Retrieval with RLS, router, budget. Number: cost per conversation before and after routing, quality beside it.
5. Azure. Terraform, deploy pipeline, WhatsApp adapter with the test number, applied in a window and destroyed. Number: measured cost of the window against the estimate.
6. Operation. Traces, metrics, load test, runbooks, chaos. Number: throughput and p95 under load, and the chaos result.

## Out of scope

Payments, plan billing, mobile app, Kubernetes, fine-tuning, multi-region, self-service tenant signup, outbound campaigns, a permanent public demo.
