# The model provider is down

## What you see

The worker logs `turn_failed` with an `error_type` of `ModelUnavailableError`, `ModelTimeoutError` or `ModelThrottledError`, and `attempt` rising. Customers get no reply for a while and then the handoff notice. In the panel, conversations appear as waiting for the team with the reason that the agent could not answer. With metrics on, `frontdesk_trigger_failures_total` rises under that error type and `frontdesk_handoffs_total` under the reason `agent_failed`.

## What the system does by itself

A turn that fails is tried again after 2, 4, 8 and 16 seconds, with its conversation held so that nothing of it runs out of order. After the fifth failure the conversation is handed to a person and the customer is told so. No reply is invented and none is lost: the customer's messages stay in PostgreSQL.

I have seen this happen once by accident: the network of the development machine dropped on 2026-11-17 while a turn was being resumed after an approval. The booking was cancelled by the tool, the model could not be reached five times, and the conversation went to the team.

And on purpose. `scripts/chaos.py model-down` restarts the worker pointed at an address where nothing answers and sends six first messages. Each customer was told that a person takes over, once, 37 seconds after writing. No model call was recorded, the six triggers went to the dead-letter queue, and after the worker was put back a new customer was answered.

A request the provider refuses as malformed is not retried and goes to a person at once. A request its content filter stops gets the fixed refusal, and is not an outage.

## What to check

Whether it is the provider or us. From the worker's environment, the deployment answers or it does not; the Azure status page and the resource's metrics say which. `ModelThrottledError` alone is the quota of the deployment and not an outage.

Throttling is the failure I can produce at will. The deployment of the demo allows 100 requests and 100,000 tokens a minute, a conversation spends three or four requests, and so about thirty conversations a minute is all it answers. A throttled call is made again where it is, after the wait the provider asks, which for this deployment was under a second, for up to 20 seconds in all; only then does the turn fail and the worker retry it. `frontdesk_model_throttled_total` counts each refused call. With three, six and twelve customers at once every one was answered and none was handed to a person, with a p95 of 7, 28 and 51 seconds. Before the call was retried in place, a throttled call failed its whole turn, and at six customers 4 of 21 were handed to a person.

## What to do

If the outage is long, stop paying for retries and stop making customers wait 30 seconds for a handoff:

```
python -m frontdesk.ops model-calls off
```

From the next turn every conversation goes straight to a person, with no model call. It needs `FRONTDESK_MIGRATIONS_DATABASE_URL`, the owner role's connection, because the application role can read this switch and cannot flip it. In the local stack: `docker compose run --rm setup python -m frontdesk.ops model-calls off`. Turn it back with `on`.

If one model is down and another deployment answers, point `FRONTDESK_MODEL` at it and restart the worker. The golden set says what to expect from each of the three that can do the job (docs/medicoes.md).

If it is throttling, the load is above what the quota answers, and customers are answered late and not lost. Lower `FRONTDESK_WORKER_CONCURRENCY` so that fewer turns run at once, or raise the deployment's capacity. What the code should do and does not: pace its own calls to the quota. It finds the limit by hitting it, and under the same quota six customers at once were answered at a little over half the rate of three.

## After it

Conversations handed over during the outage stay with the team until someone returns them to the agent in the panel. They do not come back by themselves.

## Not rehearsed

Switching the model of a running deployment on Azure, running the switch from a job there, and lowering the concurrency as a response to throttling, which I reasoned and did not run.
