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

## Planned entries

- Phase 2: block rate on adversarial cases and false block rate on benign cases, for the numeric guardrail.
- Phase 3: eval metrics before and after one real prompt change, the cost of a full suite run, and quality, cost per conversation and latency for each model the subscription can deploy.
- Phase 4: cost per conversation before and after routing, model and channel separately, with the quality metrics beside them; recall and precision at k for retrieval.
- Phase 5: actual monthly cost of the deployed environment against the estimate.
- Phase 6: throughput and p95 under load; result of the chaos scenario.
