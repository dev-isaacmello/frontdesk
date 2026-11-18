# The model provider is down

## What you see

The worker logs `turn_failed` with an `error_type` of `ModelUnavailableError`, `ModelTimeoutError` or `ModelThrottledError`, and `attempt` rising. Customers get no reply for a while and then the handoff notice. In the panel, conversations appear as waiting for the team with the reason that the agent could not answer.

## What the system does by itself

A turn that fails is tried again after 2, 4, 8 and 16 seconds, with its conversation held so that nothing of it runs out of order. After the fifth failure the conversation is handed to a person and the customer is told so. No reply is invented and none is lost: the customer's messages stay in PostgreSQL.

I have seen this happen once, by accident: the network of the development machine dropped on 2026-11-17 while a turn was being resumed after an approval. The booking was cancelled by the tool, the model could not be reached five times, and the conversation went to the team.

A request the provider refuses as malformed is not retried and goes to a person at once. A request its content filter stops gets the fixed refusal, and is not an outage.

## What to check

Whether it is the provider or us. From the worker's environment, the deployment answers or it does not; the Azure status page and the resource's metrics say which. `ModelThrottledError` alone is the tokens-per-minute quota of the deployment and not an outage.

## What to do

If the outage is long, stop paying for retries and stop making customers wait 30 seconds for a handoff:

```
python -m frontdesk.ops model-calls off
```

From the next turn every conversation goes straight to a person, with no model call. It needs `FRONTDESK_MIGRATIONS_DATABASE_URL`, the owner role's connection, because the application role can read this switch and cannot flip it. In the local stack: `docker compose run --rm setup python -m frontdesk.ops model-calls off`. Turn it back with `on`.

If one model is down and another deployment answers, point `FRONTDESK_MODEL` at it and restart the worker. The golden set says what to expect from each of the three that can do the job (docs/medicoes.md).

## After it

Conversations handed over during the outage stay with the team until someone returns them to the agent in the panel. They do not come back by themselves.

## Not rehearsed

Switching the model of a running deployment on Azure, and running the switch from a job there.
