# Phase 0: what changed from the brief, risks, and decisions still open

Status: written at the end of Phase 0. This file is a working record and is expected to shrink as decisions are made; what survives moves into ADRs.

## Where the investigation changed the plan

1. WhatsApp does not forbid general-purpose assistants in Brazil today. The terms prohibit AI providers whose AI is the primary thing offered, at Meta's discretion, and carve out countries; for +55 numbers Meta allows them and charges, after a CADE measure. The closed scope stays as a product requirement and as what keeps a tenant's agent in the ordinary category. The README must say it this way and not as a blanket prohibition.

2. WhatsApp replies cost money again since 2026-10-01: 1,000 free service messages per number per month, then BRL 0.035 each. Past the free tier one reply costs about five times the model calls behind it on the small model. So the ledger records channel cost, a turn sends one message, and "cost per conversation" in Phase 4 has two components.

3. The customer key on WhatsApp is the business-scoped user id, not the phone number.

4. A session lock on the queue is not exclusivity. Service Bus documents the lock as volatile, and a trigger whose lock was lost is delivered again while the first worker may still be running. The conversation lease with an epoch is what guarantees a single writer (ADR 0001).

5. The numeric guardrail cannot take "tool results of this turn" as the only origin without blocking legitimate replies. Origins are split by type (ADR 0006).

6. The provider contract has no temperature and no forced tool choice, because the current reasoning models reject sampling parameters and forced tools are not accepted everywhere. Fixed shapes come from structured output.

7. One graph thread per turn instead of per conversation, because of approvals that stay pending while the customer keeps talking (ADR 0002).

8. The model adapter is implemented on the vendor SDK, not on the LangChain chat models the brief mentions (ADR 0003).

9. The local queue is Microsoft's Service Bus emulator, which needs a SQL Server container beside it and reads its queues from a file. The API and worker tests run on an in-memory queue held to the same contract tests as the real one.

10. The whole system runs on one cloud, Azure, on a student subscription (ADR 0008). The brief asked for AWS hosting with two model providers. The AWS account I had could not call any model, and the student subscription cannot buy the second vendor's models, so the comparison in Phase 3 is across the models this subscription can deploy.

11. Type checking is mypy in strict mode.

## Changes I propose to the phases

Phase 1 reports two latencies: the pipeline alone with the offline model, and end to end with a real model. The first one says nothing about the product by itself; the second needs the key of the model deployment on the development machine.

Phase 2 reports the block rate on adversarial cases together with the false block rate on a benign set. One without the other can be gamed by blocking everything.

Phases 3 and 4 need a real model before the deployment phase. The model resource already exists in Foundry with one deployment. I propose a small step at the start of Phase 3: a deployment for each model the subscription has quota for, and one managed identity for GitHub Actions through OIDC that can only call inference. No infrastructure, no monthly cost, only tokens.

Phase 4 measures routing against the baseline that matters: every call on the stronger model versus the cheaper one with escalation. Which models those are comes out of the comparison in Phase 3. Routing classification to something cheaper than the cheap model saves a fraction of a tenth of a cent per turn and is not worth a claim.

## Risks

Breadth. Six phases for one person. The parts a reviewer will open are few: the guardrail, the isolation test, the eval gate, the queue design. If time runs short, I cut the MCP server, the model comparison beyond three models, and the load test detail, in that order, before I thin out any of those four.

The subscription. It is a student offer with limits the documentation does not state: regions, compute quota, and model quota that cannot be raised. It has quota for sixteen models and I have deployed and called one. If Phase 5 cannot create a resource it needs, the same Terraform goes to a pay-as-you-go subscription. This machine has no Azure CLI and no Terraform yet.

Meta's discretion. Whether a vendor of business agents counts as an "AI Provider" is decided by Meta, and the Brazil exception depends on a conciliation whose outcome I could not find. The project uses a test number only.

False blocks. The pt-BR extractor will have gaps, and every gap is a reply that goes to a person. If the false block rate is high, the fallback is the template approach recorded in ADR 0006.

Moving dependencies. LangGraph released three days before this file was written; the GenAI telemetry conventions are not stable; the MCP SDK changed its server API between major versions. Versions are pinned and upgrades go through the eval gate.

Pending approvals across deploys. An interrupted turn is resumed from a checkpoint written by an older build. The documentation does not say what is compatible. Until tested, a deploy that changes the graph expires pending approvals and tells the customer.

Single points in the demo. One database server, one replica per service, and a firewall rule that names the environment's outbound address. Acceptable for a demo and stated in the README.

Duplicate sends. No idempotency key on the WhatsApp send API. One duplicate is possible if the worker dies between the send and the commit.

A connection per conversation on the queue. Each leased conversation is a connection to Service Bus with a handshake of about 0.8 s around the turn, so worker concurrency bounds throughput. The load test has to find the limit, and ADR 0001 names the alternative.

Embedding quality in Portuguese. The subscription has quota for one embedding model, `text-embedding-3-small`. The retrieval harness measures recall on a labelled pt-BR set before I rely on it, and there is no second model to compare it with here.

## Decided after Phase 0

The project spends no real money: the student subscription has no payment method and stops when its credit ends. There is no permanent public demo: the README links a short video, and the Azure environment is applied for a measured window and destroyed. Three days of the full environment are estimated at USD 3.48 of credit. That removes the question of isolating demo visitors and keeps the daily spending cap as the only protection the window needs.

The repository is named frontdesk, and documentation file names stay as the brief wrote them.

The provider adapters stay on the vendor SDKs (ADR 0003), confirmed by the owner.

A reply that claims an action is checked against the tools of the turn: `compose` returns a declared outcome from a closed list next to the text, and `validate` compares it with what the tools did (GRD-6 in the specification).

## Decisions still open

These were taken with the default below so that work could continue. Each can be reversed at the cost stated.

1. Whether eleph goes underneath as the guard for claims about bookings, in addition to the declared outcome. "Has a booking" as "created and not cancelled since" is exactly what it expresses and proves. Its limits apply: no wall clock, so the cancellation deadline has to be emitted by the host as an event, and `z3-solver` is a hard dependency of the package today. To decide in Phase 2 with the first failing cases in hand.

2. Who the MCP server is for. Default: stdio and Streamable HTTP, run locally and in tests, not exposed in the Azure deployment. The SDK's HTTP authorization model is an OAuth resource server, which needs an authorization server I do not want to add.

3. Which models enter the comparison. The subscription has quota for `gpt-5-mini`, `gpt-4.1-mini`, `o4-mini`, `gpt-oss-120b`, two Llama models, five Phi-4 variants, three Mistral models and Codestral. Default: every one of them that can be deployed and accepts tool calling runs the golden set, and the panel shows quality, cost per conversation and latency side by side. Models that cannot call tools are listed as excluded with the reason. A model from a second vendor through its own API is an option that needs a paid key.

4. Rule check on save: synchronous with a timeout, or asynchronous with a "not checked yet" state. My recommendation is synchronous with a short timeout that falls back to "not checked".

5. Trace backend: Phoenix self-hosted as proposed in ADR 0011, or a managed one.

6. Approval scope. I assumed one pending approval per conversation and no slot held while it is pending.
