# Measurements

Every number in the README comes from an entry in this file. An entry has the date, the commit, what was measured, on what hardware or environment, the result, and the command that reproduces it. A number without a command to reproduce it does not go in.

## Phase 0, 2026-11-17

No measurement. Phase 0 is investigation and design; nothing runs yet. The figures in docs/design/cost-estimate.md are estimates from published prices and assumed token counts, and are labelled as such there. They are replaced by measured values in Phases 1, 4 and 5.

## Phase 1, 2026-11-17: latency of the pipeline, without a model

What was measured. The time from the moment the client starts sending a web chat message until the agent's reply arrives on the event stream of that conversation. The path is the real one over HTTP: signed POST to the API, row in the inbox, trigger on the queue, worker, graph with one tool call, outbox, PostgreSQL notification, server-sent event. Every message is a new conversation asking "quanto custa o corte?".

What was not measured. A language model. The worker ran the offline model, which answers in microseconds, so these numbers are the cost of everything around the model and nothing else. Latency with a real model is still to be measured. The panel's server is also outside this measurement: the script signs requests itself and talks to the API directly. And the queue was Microsoft's emulator on the same machine, not Service Bus in Azure.

Environment. The tag `phase-1`. `docker compose up` on one laptop: Intel Core i5-10300H, 8 threads, 16 GB, Ubuntu 24.04, Docker 29.8.2, with other development containers running on the same machine. One API process, one worker process handling up to six conversations at a time, PostgreSQL 18.7, Service Bus emulator 2.0.1 with SQL Server 2022, `azure-servicebus` 7.15.0. 200 messages per run.

Result.

- One conversation at a time: median 144 ms, p95 549 ms, slowest 829 ms, 5.1 messages per second.
- Ten conversations at a time: median 1,774 ms, p95 2,120 ms, slowest 2,182 ms, 5.7 messages per second end to end.

A second run of both, minutes later on the same stack, gave a median of 107 ms and a p95 of 483 ms in sequence, with one message at 3.2 s that I have not explained, and a median of 1,664 ms and a p95 of 2,052 ms in parallel at 5.9 messages per second. The medians move by about a quarter between runs; the ceiling on throughput does not.

Where the time goes. The turn itself, with the database and the offline model, is a few tens of milliseconds. The rest is the queue. Each conversation is a Service Bus session, and the worker accepts the session, takes one trigger and closes it. Timed separately against the same emulator, accepting a session took about 0.46 s and closing it about 0.33 s, both inside the SDK. A worker slot that is already waiting receives a new conversation within about 60 ms, which is why the median for one conversation at a time is low. But a slot that just finished a turn is busy for about 0.8 s before it can take the next, so six slots handle between five and six conversations per second however fast the turn is. That ceiling is the second line: ten senders against six slots queue up.

What I changed after measuring. The first version asked the queue for a batch of triggers and gave a median of 314 ms in sequence, because the SDK waits a further 0.2 s for the rest of a batch after the first message. Taking one trigger per session removed that. It also had every slot time out and reconnect at the same instant, leaving nobody listening for about a second every twenty; the waits are now staggered. With four slots instead of six the parallel run gave 3.9 messages per second and a median of 2.5 s.

What it says and does not say. Against a model call of seconds, 0.8 s of slot time per turn means more worker concurrency for the same load, not a slower reply. A namespace in Azure allows a thousand connections where the emulator allows ten, so concurrency there is a setting. I have not measured Service Bus in Azure, where the handshake crosses a network, and I make no claim about throughput until the load test in Phase 6. ADR 0001 names the design that avoids the handshake and why I did not take it.

Reproduce.

```
docker compose up --build -d
cd backend
uv run python scripts/latency.py --messages 200 --concurrency 1
uv run python scripts/latency.py --messages 200 --concurrency 10
```

## Phase 1, 2026-11-17: the same pipeline with a real model

What was measured. The same path and the same script as the entry above, with the worker calling `gpt-5-mini` on Azure OpenAI (deployment version 2025-08-07, Global Standard, resource in North Central US) instead of the offline model. Twenty messages, one conversation at a time, each a new customer asking "quanto custa o corte?". Tokens, model time and cost come from the `model_calls` ledger of those twenty turns.

Environment. The commit after the tag `phase-1` that adds the quiet window and the handling of filtered prompts. Same laptop and stack as above, worker in Porto Alegre calling the model over the public internet. Reasoning effort `low` on both nodes. Quiet window of 1.5 s, which is part of every number below.

Result.

- Time to the reply: median 8.1 s, p95 10.4 s, slowest 10.4 s.
- Of that, model calls: median 6.4 s per turn, in 3.5 calls on average (one classification, then the planner two or three times around a tool call).
- Tokens per turn, on average: 2,648 of input, 410 of them read from the provider's cache, and 221 of output.
- Cost per turn: 1,013 micro-USD on average, a tenth of a cent. The twenty turns cost USD 0.020.

What it corrects. The estimate I made before any call was 10,700 input tokens and USD 0.0038 per turn. The measured turn uses a quarter of that input and costs about a quarter. The estimate in docs/design/cost-estimate.md now carries the measured figure, for this one question; a booking conversation uses more calls and I have not averaged one.

What it says about latency. Eight seconds is slow for a chat. The pipeline around the model is about 0.15 s and the quiet window 1.5 s; the rest is three or four sequential calls to a reasoning model. Fewer calls per turn, a model that does not reason, and a shorter quiet window on channels that do not need it are the three levers, and Phase 3 measures the first two across models.

What was not measured. Quality. I read the answers of five conversations by hand (docs/verificado.md has what I saw) and that is not an evaluation. Concurrency with a real model was not measured either.

Reproduce. Needs an Azure OpenAI deployment and its key in `.env`, as `.env.example` shows.

```
docker compose up --build -d
cd backend
uv run python scripts/latency.py --messages 20 --concurrency 1
uv run python scripts/conversation.py "quanto custa o corte?" "tem horário amanhã de manhã?"
```

## Phase 2, 2026-11-18: what the reply checks block, and what they block wrongly

What was measured. The three deterministic checks every reply passes before it is sent: the numeric guardrail, the ban on discounts, and claimed actions against what the tools did. They ran over a labelled set of 86 replies in nine situations (a price question, free slots, a booking just made, a booking listed, a cancellation, the arena's prices by time of day, a greeting, opening hours, a request for a discount). A situation is the ledger a real turn would have: what the tools returned, the tenant's opening hours and what the customer wrote. A benign reply states only what its situation supports. An adversarial reply has one thing wrong: a price, a time, a date, a count, an invented discount, an action no tool performed.

Where the set comes from. I wrote the 46 adversarial replies and 30 of the 40 benign ones. The other ten benign replies are answers `gpt-5-mini` and the offline model actually gave in the conversations of the Phase 1 entry. No model runs in this measurement; it measures the checks.

Result.

- Adversarial replies blocked: 40 of 46, 87.0%.
- Benign replies blocked: 2 of 40, 5.0%.

The six adversarial replies that passed, by cause. Three state the right value next to the wrong thing: a slot that is free with the other barber, the daytime price given for the evening, the price of the other court. The check proves that a number has a source in the turn, not what it belongs to; ADR 0006 said so before any code and this is its size on this set. The other three name a wrong day that happens to fall on a weekday the business opens. That one is a weakness of my implementation and not of the idea: the opening hours enter the ledger as days, so that "abrimos de terça a sábado" can be said, and a weekday named there then vouches for a date. Telling a recurring weekday apart from a date in the extractor would close the case that writes the date in digits and leave the two that say "sexta".

The two benign replies that were blocked. One states a duration worked out from the start and end the booking tool returned, which the model is told not to do and a customer would still find reasonable. The other repeats the price the customer offered in order to decline it, and a price is accepted from tools only.

What a block costs. A blocked draft goes back to the planner once with the problem named, and only a second block hands the conversation to a person. So 5% is the rate of drafts that need a second attempt, not of conversations lost. How often a real model's second attempt passes I have not measured; that needs the eval suite of Phase 3.

What this does not say. The set is small and mostly mine, and I also specified the extractor, so it favours forms I thought of. It says nothing about how often a real model produces each kind of error. A test pins which cases pass and which are blocked, with the reason for each, so a change in the checks shows up as a diff and not as a silent change of a rate.

Reproduce.

```
cd backend
uv run python scripts/guardrail_rates.py
```

## Phase 3, 2026-11-18: the golden set, before and after a prompt change, and across models

What was measured. 32 conversations in pt-BR, each with what has to be true at its end: which tools were called, which values the last reply states, what is in the schedule, whether an approval is waiting. They cover choosing a tool, booking, moving and cancelling, prices by time of day, discounts and house rules, out-of-scope questions, attempts to trick the agent, actions that wait for the owner, and asking for a person. Each conversation runs through the real worker and graph, against a PostgreSQL started for the run, at a fixed instant (a Wednesday at 07:00 in São Paulo), with no quiet window. The verdict of a case is code: the reply is read by the same extractor the guardrail uses and the schedule is read from the database. No model judges a model.

Why several runs. A model does not answer the same way twice. Every figure below is three runs of the same model with the same prompts, and I give the three counts, not only their mean.

Before and after one prompt change, on `gpt-5-mini`. With the prompts as they were, the planner asked the customer for a day and a time before stating any price, and did not act on a request to move a booking. I added three instructions: quote with the current date instead of asking, take a weekday as its next date, and act at once when a single booking matches the request.

- Before (prompts `9f2f84565883`): 28, 29 and 27 of 32. Mean 28.0.
- After (prompts `c9ecc03865a9`): 31, 32 and 30 of 32. Mean 31.0.
- Cost per conversation went from USD 0.00122 to USD 0.00132, and the median model time per turn from 7.2 s to 8.5 s. The agent now calls a tool where it used to ask a question.

Across models, all with the prompts after the change.

- `gpt-oss-120b`: 31, 31 and 31 of 32. USD 0.00061 per conversation. 2.6 s of model time per turn, median.
- `gpt-5-mini`: 31, 32 and 30 of 32. USD 0.00132 per conversation. 8.5 s.
- `gpt-4.1-mini`: 31, 28 and 28 of 32. USD 0.00079 per conversation. 3.4 s.

What I take from it. On this set `gpt-oss-120b` does as well as `gpt-5-mini` at less than half the cost and a third of the model time, so it is the model I would run this agent on, and it is the model the gate in CI uses. The three cases it fails are different in each run: twice it answered a clear booking request without booking, once it gave up on a quote. `gpt-4.1-mini` loses most of its cases in one place: it sends requests about other customers' bookings to a person instead of declining them, which I count as a failure of the expected behaviour and is also the safest way to be wrong.

Models left out. Six models could be deployed on the student subscription and three cannot do the job: Llama 3.3 70B rejects a request with more than one tool, Phi-4 rejects structured output and tool calling, Phi-4 mini ignores the tools. The Mistral models and Llama 4 Scout are sold through Azure Marketplace, which refuses a subscription with no payment method, and `o4-mini` has quota and can no longer be deployed. The list with each answer is in evals/models.json.

The gate, seen working. A pull request that touches prompts, graph, tools, providers or checks runs the set on `gpt-oss-120b` and is compared with a baseline of the three runs above, in which a case counts as passing only if all three passed it (29 of 32). Two pull requests were opened to try it. The first removes three instructions from the planner prompt; I expected it to fail and it passed with 30 of 32, one stable case lost, which the gate tolerates (https://github.com/dev-isaacmello/frontdesk/pull/1). The second tells the agent to ask for confirmation before acting; it passed 26 of 32, lost four stable cases and the job failed, with the cases named in a comment (https://github.com/dev-isaacmello/frontdesk/pull/2). Every unit test passes on both, because they run on a scripted model.

What it cost. The 14 runs recorded in evals/runs cost USD 0.43 of the subscription's credit, for 461 turns. A full run of the set costs between two and four cents depending on the model. The runner adds an estimate of the next run to that total and refuses to start past USD 5; the two runs in CI are not in the total, because their results are not committed.

What this does not say. Thirty-two conversations written by one person, who also wrote the prompts, find the failures that person thought of. Three runs show that results vary and are too few to put a number on how much. The model time per turn is the sum of the calls of a turn as the adapter timed them, from one laptop, with three models sharing the network at the same moment. And passing a case means the checks I wrote were satisfied, not that a customer would have been happy with the reply.

Reproduce. Needs the key of the model resource in `.env`. The first command costs about two cents.

```
cd backend
uv run python scripts/run_evals.py --model gpt-oss-120b
uv run python scripts/summarize_evals.py
uv run python scripts/make_baseline.py --model gpt-oss-120b
```

## Phase 4, 2026-11-18: retrieval, what routing saves, and two defects the measuring found

Retrieval, on a labelled set. 30 questions in pt-BR across the two tenants. 24 name the one entry of the knowledge base that answers them; 6 are answered by a tool or are a greeting, and the right retrieval for them is nothing. Each question goes through the same search a turn uses, three results at most, inside the tenant's transaction.

- `text-embedding-3-small`, threshold 0.65: the right entry is first for 22 of 24 questions (0.917) and among the three for all 24 (1.000). Of the entries shown for those questions, 0.533 are the one that answers. For 2 of the 6 questions with no answer in the base nothing is retrieved (0.333).
- The threshold is the lowest that finds every answer. At 0.55 the same model finds 19 of 24 with a precision of 0.760; at 0.75 it finds all with 0.358 and is never quiet.
- The offline embedder, which hashes words and is what the stack runs on with no credentials: 17 of 24 (0.708), precision 0.773, quiet for 2 of 6. It misses what shares no word with its answer, such as "onde vocês ficam?" for the address.

What retrieval does to the agent. The golden set gained five conversations that only the knowledge base can answer, one of them asking the barbershop for a fact that is true of the arena, and is now 37. The runner embeds and retrieves with the deployment that ships. On `gpt-oss-120b`, three runs each way, at the same commit:

- With retrieval: 35, 36 and 35 of 37. The five new conversations pass in every run, and the 32 older ones pass 30, 31 and 30 times.
- Without retrieval: 32, 31 and 32 of 37. One of the five new conversations passes, the one whose right answer is not knowing, and the 32 older ones pass 31, 30 and 31 times.
- Cost per conversation is USD 0.00057 with and USD 0.00056 without. The median model time per turn goes from 2.1 s to 2.6 s, which is the embedding call and three more short texts in the prompt.

So retrieval answers what it was added for and I could not measure a loss on what the agent already did. The second half of that is weaker than it reads: one case, booking in a single message, failed in all three runs with retrieval and in two of the three without.

What routing saves. Three configurations of the same 37 conversations, three runs each, all with retrieval.

- Every call on `gpt-5-mini`: 34, 34 and 37 of 37. USD 0.00114 per conversation. 8.3 s of model time per turn, median.
- The classifier on `gpt-oss-120b` and the planner on `gpt-5-mini`: 37, 36 and 36 of 37. USD 0.00100 per conversation. 6.8 s.
- Every call on `gpt-oss-120b`: 35, 36 and 35 of 37. USD 0.00057 per conversation. 2.6 s.

Sending the classifier to the cheaper model takes 13% off the cost of a conversation and 1.5 s off a turn, with no fewer conversations passed. Sending everything to it halves the cost and takes two thirds off the time, and passes as many. The router is built and tested, and the default configuration does not use it by node: on this subscription the cheapest model that can call tools is also the one that does the job best, so every call goes to it. What the router is for here is the tenant's plan and a spent budget. `gpt-4.1-mini`, for the comparison in the panel: 34, 33 and 35 of 37, USD 0.00065, 3.3 s.

Model and channel, separately. A turn on `gpt-oss-120b` costs USD 0.00055 in model calls. On the web chat the channel costs nothing and the message records zero. On WhatsApp a reply is one service message: the first 1,000 a month per number are free and each one after that is BRL 0.035, about USD 0.0068 on Meta's rate card of 2026-10-01, which is twelve times the model calls behind it. The adapter records the charge on each message when Meta reports the delivery as billable. No message was sent through it yet, so there is no measured channel cost: that belongs to the window of Phase 5.

Two defects that only showed up under repetition.

- The check for claimed actions read "até 10 minutos depois do horário marcado" as a booking nobody made. With the knowledge base the agent started saying that, and 4 of 10 runs of one question ended with a person being called. After the fix the same question passed 40 times of 40. The labelled set of replies grew by nine about the knowledge base and now measures 44 of 50 adversarial replies blocked (88.0%) and 3 of 45 benign replies blocked (6.7%). One of the three is new and stays: "ainda será atendido no horário marcado" is refused, because the same words are how a booking that was never made would be confirmed.
- `gpt-oss-120b` returned a NUL byte inside a reply in 4 of about 330 conversations. PostgreSQL refuses that byte, the turn failed at its last write and was run again from the start. I could not reproduce it on demand: 54 further runs of the conversations it had hit produced none, so I know its rate and not its position in the text. Control characters are now removed from every model response, and from customer and owner input, where the same byte returned HTTP 500.

One thing I saw and did not fix. In 4 of the 444 conversations of these runs a customer who should have had an answer got the fixed refusal. That is what the agent sends when the provider's content filter stops a request, and nothing in a run says which request it was. It needs a log line of its own, which is work for Phase 6.

What it cost. The 26 runs now recorded under evals/runs cost USD 0.80 of the subscription's credit, for 917 turns. About USD 0.50 more went on runs that are not recorded: eight made before the two fixes and discarded, six made to catch the NUL byte, three without retrieval, and the repetitions above.

What this does not say. The 30 retrieval questions and the knowledge base were written by the same person on the same day, the base has eight entries per tenant, and the threshold was chosen on the questions it is then reported on. Three runs per configuration separate a 13% difference in cost, which is arithmetic over token counts, far better than they separate 35 from 36 conversations passed. Cost per conversation is over 37 conversations here and over 32 in the Phase 3 entry, and the five added ones are short, so the two entries cannot be subtracted from each other. All figures are from one laptop calling one region.

Reproduce. The first two commands need Docker and nothing else; the others need the key of the model resource in `.env` and cost a few cents each.

```
cd backend
uv run python scripts/retrieval_rates.py
uv run python scripts/guardrail_rates.py
uv run python scripts/retrieval_rates.py --model text-embedding-3-small
uv run python scripts/run_evals.py --model gpt-oss-120b
uv run python scripts/run_evals.py --model gpt-oss-120b --embedding-model none --no-save
uv run python scripts/run_evals.py --model gpt-5-mini
uv run python scripts/run_evals.py --model gpt-5-mini --classify-model gpt-oss-120b
uv run python scripts/summarize_evals.py
```

## Phase 6, 2026-11-18: throughput and latency under load, and three failures made on purpose

What was measured. How many customers the stack answers per second and how long each waits, at rising numbers of customers at once, first with the offline model and then with a real one. Then what the customers got when the worker was killed and when the model could not be reached. A level of load is a number of customers; each opens a new web chat conversation, asks a price, waits for the reply on the event stream and starts over, for 60 seconds, alternating between the two tenants. The latency is from the start of the POST to the reply.

What was not measured. Azure. The queue is Microsoft's emulator, the database a container, and the load generator runs on the same laptop as the stack and takes CPU from it. One worker process with six slots. Only the web chat channel and only a price question, which makes no booking, so nothing here exercises a write being retried. Each level ran once in the reported run.

Environment. The tag `phase-6`. The laptop of the Phase 1 entry: Intel Core i5-10300H, 8 threads, 16 GB, Ubuntu 24.04, Docker 29.8.2, other development containers running. PostgreSQL 18, Service Bus emulator 2.0.1, a quiet window of 1.5 s before a turn starts. Metrics on, pushed to Prometheus 3.16.0, and traces off during the load. The real model is `gpt-oss-120b` with `text-embedding-3-small` for retrieval, on a Global Standard deployment whose limits, read with `az cognitiveservices account deployment list`, are 100 requests and 100,000 tokens per minute.

Traces and metrics, checked against real backends first. One message sent through the web chat to the real model arrived in Phoenix 21.0.0 as one trace of 21 spans: the request, the worker's span as its child across the queue, each node of the graph, four chat calls and one embedding with their tokens, two tool calls and the send. After another message Prometheus held the series the worker pushed, for example 3,951 input tokens under the node `plan` and the tenant's id. Until then both had only been tested in memory.

Result, offline model.

- 1 customer: 38 replies in 61 s, 0.62 per second, median 1,575 ms, p95 1,661 ms, slowest 1,783 ms.
- 6 customers: 224 replies, 3.64 per second, median 1,639 ms, p95 1,772 ms, slowest 2,043 ms.
- 12 customers: 351 replies, 5.66 per second, median 2,037 ms, p95 2,657 ms, slowest 3,695 ms.
- 24 customers: 366 replies, 5.76 per second, median 4,097 ms, p95 4,183 ms, slowest 5,279 ms.

Every customer was answered at every level. The floor is the quiet window: of the 1.57 s of a reply with nobody else in line, 1.5 s is the worker waiting to see whether the customer is still typing, and the trace of one such reply has the request at 0.12 s, the nodes at 0.03 s and the send at 2 ms. The ceiling is the one Phase 1 found, between 5.6 and 5.8 conversations per second for six slots, because a slot spends about 0.8 s opening and closing a Service Bus session around each turn. Past it, more customers only wait longer: the metrics put the 95th percentile of the wait for a turn at 4.8 s over the run, while no node of the graph had a p95 above 48 ms.

The row every model call updates. ADR 0013 keeps the deployment's total of the day in one row and asked this test whether that row is contended. A sample of PostgreSQL once a second found a session waiting for a lock in 7 of 260 samples, never more than 3 at once, at up to 5.8 turns per second with three model calls each. It is visible and it is not what limits anything here.

Result, real model.

- 3 customers: 33 answered in 66 s, 0.50 per second, median 5,024 ms, p95 9,046 ms, slowest 9,632 ms. Nobody handed to a person.
- 6 customers: 17 answered and 4 handed to a person, median 12,449 ms, p95 47,357 ms.
- 12 customers: 24 answered and 4 handed to a person, median 24,049 ms, p95 71,962 ms.

Here the limit is the deployment's quota and not the pipeline. A conversation spends three or four chat requests and the deployment allows 100 a minute, so about thirty conversations a minute is what it answers, and three customers at once already ask for that. Above it the provider answered 99 calls with a throttling error during the run. The worker did what it is built to do, retry and then hand over, and nobody was left without an answer of some kind. What it does badly: a turn's five attempts are spread over 30 seconds and the quota is counted over 60, so a turn can fail five times inside one spent window; and each retry starts the turn over and spends requests again, which feeds the throttling. Eight customers were told a person would take over when waiting longer would have got them an answer. I did not change this. Inside a turn, by the metrics, the 95th percentile of a model call was 1.3 s to classify, 1.2 s to embed and 2.6 s to plan, and every other node was at or under 27 ms.

Result, failures.

- Worker killed before its turns started. Twelve first messages, then SIGKILL to the worker one second later, while every turn was still inside its quiet window. The worker stayed down 14 s. All twelve customers were answered, each exactly once, the last one 4.2 s after the restart.
- Worker killed in the middle of its turns, real model. Six first messages, SIGKILL four seconds later, with the six turns under way. All six were answered, each exactly once, and no message was left without a turn. The last reply came 173 s after the restart. A turn reserves its conversation for three minutes so that two workers never run it at once, and nothing renews or releases that reservation when the process dies, so the trigger that comes back waits for it to run out. The ledger has 40 model calls for these six conversations where 24 to 30 would do: the calls of the turns that died were paid for and are recorded.
- Model unreachable. The worker restarted with the model's address pointing where nothing listens, then six first messages. Each customer was told that a person takes over, once, 37.2 s after writing: 30 s of waiting between five attempts, plus the quiet window and the attempts. No model call was recorded. The metrics counted 30 failed deliveries under `ModelUnavailableError`, 6 dead letters and 6 handoffs with the reason `agent_failed`. With the worker put back, a new customer was answered in 2.4 s. The six conversations stayed with the team, which is the design.

What it says and does not say. On this machine the pipeline around the model has room for about 5.7 conversations per second per worker of six slots, and a real model on a student quota uses a tenth of that. The first thing to run out is the provider's requests per minute, and the way this worker retries makes running out worse than it has to be. A worker that dies loses no message and repeats none, and costs its customers up to three minutes. None of this is Azure: there the session handshake crosses a network, the queue allows more connections, and a second worker replica is possible, which I have not run.

Seen once and not explained. In an earlier run of the same script, the level of one customer had at least two of 34 replies above 3 s, with a slowest of 4,151 ms. In three later runs of that level, with 56, 93 and 38 replies, none passed 1.9 s. The Phase 1 entry has the same kind of outlier. I ran the later ones with tracing on to catch one and did not.

Reproduce.

```
FRONTDESK_MODEL_PROVIDER=offline FRONTDESK_MODEL=offline FRONTDESK_EMBEDDING_MODEL=offline \
FRONTDESK_OTLP_METRICS_ENDPOINT=http://prometheus:9090/api/v1/otlp/v1/metrics \
  docker compose --profile metrics up --build -d
cd backend
uv run python scripts/load.py --levels 1,6,12,24 --seconds 60 \
  --prometheus http://127.0.0.1:9790 --sample-locks --out ../ops/load/offline.json
uv run python scripts/chaos.py worker-killed --customers 12 --out ../ops/chaos/worker-killed.json
uv run python scripts/chaos.py model-down --customers 6 --out ../ops/chaos/model-down.json
```

The chaos script puts the worker back with `docker compose up`, so it needs the same variables in its environment as the stack was started with. With a real model in `.env` and the three model variables left out of the first command:

```
uv run python scripts/load.py --levels 3,6,12 --seconds 60 \
  --prometheus http://127.0.0.1:9790 --sample-locks --out ../ops/load/gpt-oss-120b.json
uv run python scripts/chaos.py worker-killed --customers 6 --kill-after 4 \
  --out ../ops/chaos/worker-killed-mid-turn.json
```

The reports of the runs above are in [ops/load](../ops/load) and [ops/chaos](../ops/chaos). The real-model runs behind this entry, two of the load, one of the chaos and the messages that checked the traces, cost USD 0.15 of the subscription's credit by the ledger.

## Phase 6, 2026-11-18, later: the two defects of the entry above, fixed and measured again

What was measured. The same two scenarios that showed the defects, on the same machine and stack, after each change: the worker killed in the middle of six turns, and the load of 3, 6 and 12 customers at once on `gpt-oss-120b`.

The dead worker. A turn reserved its conversation for three minutes and nothing renewed or released that. Now the reservation is 45 seconds and a running turn renews it every 15. With the worker killed four seconds into six turns, all six customers were answered, each exactly once, and the last one 43.4 s after the worker was back, where it had been 172.7 s. A customer whose worker dies in the middle of their turn now waits at most one reservation. Commit `fc91bd1`.

Throttling, and a hypothesis the measurement refuted. I read the first result as a retry too short for the quota's minute, made the worker hold a throttled turn for as long as the provider asks, and ran the load again. Six customers: 28 answered and 2 handed to a person. Twelve: 20 and 2. No better than chance, and the log said why: in 84 throttled calls the wait Azure asked for was between 0.1 and 1.0 s, always under the two seconds the worker already waited. The quota is not a window to sit out.

What was wrong was where the retry happened. A throttled call failed its turn, and the turn started over, spending again the calls that had already been answered while the deployment was over its rate. The call is now made again where it is, after the wait the provider asked, for up to 20 s in all before the turn fails as before. Commit `b199817`. The same load after it:

- 3 customers: 37 answered, median 4,805 ms, p95 7,062 ms.
- 6 customers: 25 answered and none handed to a person, median 16,728 ms, p95 27,616 ms. Before: 17 and 4, p95 47,357 ms.
- 12 customers: 30 answered and none handed to a person, median 33,182 ms, p95 51,166 ms. Before: 24 and 4, p95 71,962 ms.

No turn failed in the whole run. The provider refused 785 calls, which waited in place and were answered, and each is counted in `frontdesk_model_throttled_total`.

What is still not right. Six and twelve customers got 0.30 replies per second and three got 0.54. More load, less answered: a refused call appears to count against the requests per minute, so asking again costs quota too. The next step is for the worker to pace its own calls to what the deployment allows instead of finding the limit by hitting it. I have not built that, and I have not confirmed in Azure's documentation that a refused call is counted.

Reproduce. The commands of the entry above, at the commit named.

## Phase 5, 2026-11-18: the environment applied on Azure, and what the first apply found

What was measured. Whether the Terraform, the deploy workflow and the system itself work on Azure, which until this day had only passed `terraform validate`; and the same load script as Phase 6, against the deployment. This entry is written with the window still open. Its cost against the estimate and the first exchange with WhatsApp are not in it yet, and it says so again at the end.

Environment. An Azure for Students subscription, region North Central US. Three container apps of 0.5 vCPU and 1 GiB with one replica each, a setup job, PostgreSQL flexible server 18 on B1ms, Service Bus Standard with a session queue, Key Vault, a Basic registry and a log workspace. `gpt-oss-120b` and `text-embedding-3-small` in the same region. Terraform 1.17.2, azurerm 4.81.0, azapi 2.14.0. The first resource was created at about 13:00 UTC.

What works, as observed. The deploy workflow signs in to Azure with a federated identity and no stored secret, builds and pushes both images, runs the job that migrates and seeds, and rolls the three apps; its run on commit `3b4b896` did all of it. A customer message sent to the public API was answered through the real Service Bus and by the model, which the worker calls as its managed identity with no key: a price in 8.2 s on a cold path, and a question the knowledge base answers in 3.4 s. Service Bus refuses connection strings. After the last change `terraform plan` proposes nothing.

What the first apply found. Five things were wrong, none of which `terraform validate` or the local stack could have shown.

- The subscription refuses a named availability zone for the database in this region. The server is now created without one.
- Azure created the Container Apps environment as "express", a shared tier with no jobs and no Key Vault references, on which two of the apps and the job were refused. Its documentation says a template gets a standard environment unless it asks for express; this one did not ask. azurerm has no argument for the mode, so the configuration sets it through the resource API. The change took Azure about twenty-five minutes.
- Without a virtual network the environment leaves through 181 addresses of a pool shared between customers, where ADR 0010 expected one or two of its own. PostgreSQL creates firewall rules one at a time, at 64 seconds each by the nine I let it create: three hours for a list that kept nobody in particular out. The database now has the rule for any Azure service, and the ADR says what that gives up.
- On Azure the `public` schema of a new database does not belong to the database's owner, so the owner role could not create its first table. The bootstrap now grants it, and a test gives a local cluster the same ownership.
- The role that lets the deploy identity change the apps does not cover jobs. It now holds the jobs role on the setup job alone.

Result under load, from a laptop in Brazil against the deployment, 60 s per level, one run.

- 1 customer: 13 answered, median 4,372 ms, p95 6,256 ms.
- 3 customers: 38 answered, 0.57 per second, median 4,487 ms, p95 9,798 ms.
- 6 customers: 22 answered and none handed to a person, median 17,008 ms, p95 29,131 ms.

These are the numbers of the local stack on the same model, within what one run can tell apart: 4,805 and 7,062 ms at three customers, 16,728 and 27,616 at six. The limit is the same deployment quota in both places. So the real Service Bus, across a network, did not add a delay I can see at this load, which is the question the Phase 1 entry left open. It is not an answer about throughput: one worker replica, a model quota that binds at three customers, and no run without a model on Azure.

What it does not say yet. What the window cost: Cost Management answers for this subscription, and showed nothing for the new resource group a few hours in. Whether Meta's webhook signature verifies and a message goes out, which waits for the app's secret and a token. And nothing here was run with a second worker replica, with metrics exported, or with the alert on dead letters made to fire.

Reproduce. `infra/README.md`, then:

```
export FRONTDESK_WEBCHAT_SECRET="$(az keyvault secret show --vault-name <vault> --name webchat-secret --query value -o tsv)"
cd backend
uv run python scripts/conversation.py --base-url <api_url> "quanto custa o corte amanhã às 10h?"
uv run python scripts/load.py --base-url <api_url> --levels 1,3,6 --seconds 60 \
  --out ../ops/load/azure-gpt-oss-120b.json
```

## Planned entries

- Phase 5: what the window cost against the estimate, and the first exchange with WhatsApp.
