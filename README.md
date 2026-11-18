# Frontdesk

A small business answers the same questions and books the same slots all day on WhatsApp. This system answers and books for it, inside limits the business sets, and hands the conversation to a person when it should not decide alone. It is multi-tenant and built to run on Azure.

This is a portfolio project. The two businesses in it are fictional. I am building it in phases, and this file says what exists today, not what is planned. The plan is in [docs/spec.md](docs/spec.md).

## Status

Five of the six phases are done, and the one that is not is the deployment. The agent runs on one machine with the controls that make its answers safe to send, an evaluation that says how well it does and stops a pull request that makes it worse, a knowledge base per business, limits on what the models may cost, and traces, metrics, a load test and rehearsed failures. Phase 5, the Azure environment and the WhatsApp number, is written and has not been applied.

What works now. A customer writes in a web chat. The message is authenticated, stored once and put on a queue. A worker runs one turn of an explicit agent graph that can list services, quote prices by time of day, check availability, book, reschedule and cancel. Before a reply is sent, code checks it: every amount, time, date, duration and count has to come from a tool of that turn, the opening hours or the customer's own words; no discount is offered; no booking is announced that a tool did not make. A draft that fails goes back to the planner once, and a second failure hands the conversation to a person. Cancelling or moving a booking on short notice waits for the owner: the turn pauses, the customer is told, and the decision resumes it, in whichever worker receives it. The owner has a panel with the conversations, how each reply was made step by step, the approval queue, an editor for house rules that says which rules contradict the fixed policy, what the agent did and cost day by day, and the comparison of models. Two tenants with different services, prices and hours live in one PostgreSQL, isolated by row-level security.

Knowledge and cost. What a business knows and its catalog does not, such as the address or how late a customer may arrive, is kept as short texts and retrieved into the turn by an exact vector search that row-level security confines to the tenant. Each business has a monthly budget for model calls: at the budget it is served by a cheaper model, past it by a person. The whole deployment has a daily cap, and a switch an operator can flip to stop every model call.

The evaluation. A golden set of 37 conversations in pt-BR runs through the real worker against a real model and is judged by code. A pull request that touches prompts, graph, tools, providers or checks runs it in CI, signed in to Azure with a federated identity and no stored key, and fails when two cases that pass in every run on main no longer do. Two pull requests show it: [one](https://github.com/dev-isaacmello/frontdesk/pull/1) trims the prompt, which I expected to fail and which the gate lets through with the numbers; [the other](https://github.com/dev-isaacmello/frontdesk/pull/2) adds an instruction that sounds prudent, and the gate stops it and names the four conversations it broke.

Operation. Every message produces one OpenTelemetry trace from the request to the reply, across the queue, and the API and the worker push metrics: how long each node took, tokens and cost per tenant, tool errors, blocked drafts, handoffs, how long a message waited for its turn, failed deliveries and dead letters. Neither carries what a customer wrote or is called. Two optional containers show them locally, `docker compose --profile traces` for Phoenix and `--profile metrics` for Prometheus. A script puts the stack under load and another breaks it on purpose and checks what the customers got; [docs/runbooks](docs/runbooks) says what to look at and do in four failures, two of them rehearsed that way.

Written and not yet run against the real thing. The WhatsApp channel is tested against the payloads in Meta's documentation and has not exchanged a message with Meta. The Terraform of the Azure environment in [infra](infra) passes validation and has never been applied, and so nothing here has run on Azure except the models. Phase 5 ends with the environment applied for a measured window and destroyed; that has not happened.

What does not exist. A screen to edit the knowledge base, which comes from the seed. A dashboard or an alarm over the metrics, apart from one alert on dead letters written in the Terraform. Without a model key the agent runs on a deterministic offline model that understands a handful of phrasings by keyword. It is there so the pipeline can run and be measured with no cloud account, and nothing about answer quality should be read from it.

## Run it

```
docker compose up --build
```

Then open http://localhost:3700 and talk to one of the two businesses. Docker is the only requirement. The first run downloads about 3 GB of images, most of it the SQL Server that Microsoft's Service Bus emulator needs, and the stack uses about 1.7 GB of memory.

To talk to a real model instead of the offline one, put the endpoint and key of an Azure OpenAI deployment in `.env`, as `.env.example` shows, and start it again.

The owner's panel is at http://localhost:3700/painel. The two demo owners are `dono@navalha.example` and `dono@ponto-final.example`, and their password is the value of `FRONTDESK_DEMO_OWNER_PASSWORD`, whose local default is in `compose.yaml`. An approval only appears when a customer asks to cancel or move a booking of the barbershop that starts within three hours.

## Architecture

```mermaid
flowchart TD
    browser[Browser] --> panel[Panel server, Next.js]
    panel -- signed request --> api[API, FastAPI]
    api -- store once --> pg[(PostgreSQL: inbox, outbox, row-level security)]
    api -- trigger --> queue[[Service Bus, one session per conversation]]
    queue --> worker[Worker]
    worker --> turn[Turn graph: classify, retrieve, plan, execute, validate]
    turn --> tools[Scheduling tools]
    turn --> model[Model provider port]
    tools --> pg
    worker -- reply to outbox --> pg
    turn --> checks[Reply checks: numbers, discounts, claimed actions]
    turn -. pause for approval .-> pg
    pg -. notify .-> api
    api -. event stream .-> panel
    panel -- owner routes --> api
```

The decisions behind this, each with the alternatives I rejected and what the choice costs, are in [docs/adr](docs/adr). What to look at and what to do when the queue grows, the model provider is down, the webhook signature fails or cost passes its budget is in [docs/runbooks](docs/runbooks). Three I would read first:

- [0001](docs/adr/0001-postgres-inbox-and-session-queue-as-trigger.md): PostgreSQL is the inbox and the queue only carries a trigger, because a lock on a queue is not exclusivity. It also says what a session per conversation costs in latency.
- [0004](docs/adr/0004-row-level-security-with-transaction-scoped-tenant.md): tenant isolation by row-level security with a setting that lives for one transaction.
- [0006](docs/adr/0006-deterministic-numeric-guardrail.md): the numeric guardrail as deterministic code, with what it blocked and what it missed when measured.

Facts about third-party services that the design depends on were checked against their documentation and recorded with links and dates in [docs/verificado.md](docs/verificado.md), including what the documentation did not settle.

## Measured

Every number here comes from [docs/medicoes.md](docs/medicoes.md), which has the environment and the command that reproduces it.

Latency of the pipeline without a model, from message sent to reply on the stream, on one laptop against the Service Bus emulator: median 144 ms and p95 549 ms with one conversation at a time; median 1.77 s and p95 2.12 s with ten at a time, at 5.7 messages per second. This is the overhead around the model, and most of it is the queue: a session per conversation costs a connection handshake on every turn. The measurement entry explains it and ADR 0001 names the faster alternative I did not take. With `gpt-5-mini` on Azure OpenAI answering, the same path takes a median of 8.1 s and a p95 of 10.4 s for a price question, of which 6.4 s are three or four sequential model calls and 1.5 s is the wait for the customer to finish typing. One such turn costs a tenth of a cent.

The golden set, three runs per model: `gpt-oss-120b` passes 35, 36 and 35 of 37 conversations at USD 0.0006 per conversation and 2.6 s of model time per turn; `gpt-5-mini` 34, 34 and 37 at USD 0.0011 and 8.3 s; `gpt-4.1-mini` 34, 33 and 35 at USD 0.0006 and 3.3 s. One change of prompt had taken `gpt-5-mini` from 28, 29 and 27 of 32 to 31, 32 and 30. Three more models were deployed and cannot call tools the way the agent needs.

Retrieval, on 30 labelled questions: the entry that answers is among the three retrieved for 24 of 24, and first for 22. On the golden set it turns five conversations that could not be answered into five that are, with no loss I could measure on the other 32.

Routing: sending only the classifier to the cheaper model takes 13% off the cost of a conversation on `gpt-5-mini`, with as many conversations passed. Sending every call to `gpt-oss-120b` halves it, which is why that is the default and the router is used for plans and spent budgets instead.

Under load, on the same laptop and emulator: with the offline model one worker of six slots answers 5.7 conversations per second however many customers wait, with a p95 of 2.7 s at twelve customers at once and 4.2 s at twenty-four, and nobody unanswered. With `gpt-oss-120b` the limit is the deployment's 100 requests per minute: three customers at once are all answered with a median of 5.0 s and a p95 of 9.0 s, and at six the provider throttles, 17 are answered and 4 are handed to a person. The way the worker retries makes that worse than it has to be, and the entry says how.

Failures made on purpose. A worker killed before its turns started: twelve of twelve customers answered once, the last 4.2 s after the restart. A worker killed in the middle of six turns: six of six answered once, and the last 173 s after the restart, because a dead turn's reservation of its conversation lasts three minutes. The model unreachable: six of six told after 37 s that a person takes over, and service back for the next customer when the model is.

The reply checks, on a labelled set of 95 replies: 44 of 50 adversarial replies blocked (88.0%) and 3 of 45 benign replies blocked (6.7%). Half of the misses are a right value next to the wrong thing, which the check cannot see by design; the other half are a weakness of mine that the entry describes.

## Tests

```
make check
```

The backend has about 600 tests and they run against a real PostgreSQL in a container, including the checkpointer that keeps a turn paused for approval. The queue has one contract suite that runs against Azure Service Bus in Microsoft's emulator and against the in-memory queue the other tests use, so the stand-in cannot drift from the real thing. The other test doubles are at the external edges: the model provider and the channel. Tests cite the requirement they prove by its id in the specification, for example `TEN-2` for tenant isolation and `BOOK-3` for the constraint against double booking.

## What I chose not to build and why

A permanent public demo. The always-on environment is estimated at USD 85 per month and the project runs on a student subscription with USD 100 of credit. The deployment will be applied for a measured window and destroyed, and a short video will stand in for the link. The estimate is in [docs/design/cost-estimate.md](docs/design/cost-estimate.md).

A model that judges the model. Every expectation of the golden set is checked by code, against the reply as the guardrail's extractor reads it and against the database. It keeps the evaluation cheap and repeatable, and it means the set only asks what code can verify.

A generic ReAct agent from a library. The turn is an explicit graph, so every step is a place where a limit can be enforced and a number can be measured.

LangChain model wrappers. The model is called through the vendor SDK behind one small port. The reasons are in [ADR 0003](docs/adr/0003-provider-port-over-vendor-sdks.md).

A second cloud or a second model vendor. Everything runs on Azure, and the model comparison is across the models one student subscription can deploy. [ADR 0008](docs/adr/0008-one-cloud-azure.md) says why, including the part that was decided by the account and not by me.

A private network. The demo reaches the database and the queue over public endpoints guarded by identity and a firewall, which is cheaper and weaker than a virtual network. [ADR 0010](docs/adr/0010-public-endpoints-behind-identity-and-a-firewall.md).

An approximate vector index. With a few dozen texts per business an exact scan is fast, and it is the only search whose result cannot depend on another tenant's rows. [ADR 0012](docs/adr/0012-exact-vector-search-under-row-level-security.md) names the point where that stops being true.

Token streaming to the customer. A reply is checked before it is sent, so nothing is shown that might be retracted.

Payments, plan billing, a mobile app, Kubernetes, fine-tuning, multi-region, self-service signup and outbound campaigns are out of scope.
