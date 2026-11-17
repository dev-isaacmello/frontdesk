# 0001. Postgres is the inbox, the Service Bus queue is a per-conversation trigger

Status: accepted

## Context

A webhook has to answer fast and must not lose or duplicate a message. Two messages of the same conversation must never be processed in parallel, different conversations must scale out, a burst from one customer should become one model call, and a failing message must end in a dead-letter queue with an alarm.

What a session-enabled queue on Azure Service Bus gives and does not give, checked in docs/verificado.md:

- A session is given to one receiver at a time and its messages are delivered in order. Messages of other sessions go to other receivers meanwhile. That is ordering and a lock per conversation.
- The session lock lasts for the queue's lock duration, one minute by default and five at most, and has to be renewed for longer work. The documentation calls the lock volatile: it is lost on a service update or a dropped connection, and the session is then given to another receiver while the first may still be working. The queue hands out a lock; it does not guarantee exclusivity.
- Duplicate detection drops a second message with the same message id inside a window of ten minutes by default. A redelivery after the window is not caught by the queue.
- The delivery count grows when a message is abandoned or its lock expires, not when a receiver closes the session with messages unsettled. Past the maximum delivery count the message moves to the dead-letter queue and the receiver goes on with the rest of the session.
- An abandoned message is delivered again at once. There is no delay built into redelivery.
- Sessions and duplicate detection need the Standard tier and cannot be switched on after the queue exists.

## Decision

The webhook writes the raw event to `inbound_events` under a unique key on the provider message id, and only then sends a queue message whose session id is the conversation id and whose message id is a hash of the channel account and the event id. The queue message carries ids, not content.

The worker treats a queue message as "this conversation has work". It accepts the next session that has messages, which is a lease on that conversation, takes one trigger, reads every unprocessed inbound message of the conversation from Postgres and runs one turn over them. Then it closes the session. Triggers still waiting behind the first make the queue offer the conversation again, and usually find nothing left to do.

On top of the session, the worker takes a lease on the conversation row with an epoch, and the turn's final writes check it, so a worker that lost its session lock cannot commit. This second lock arrives in Phase 2 together with the quiet window that groups a burst.

Idempotency comes from the database: the unique key on the inbound event, the unique outbox row per turn and sequence, and the idempotency key on bookings. The queue's duplicate detection is an optimization, not the guarantee.

A failed turn is retried by holding the session for a pause that grows with the attempt (2, 4, 8, 16, then 30 seconds) and then abandoning the message, which counts the delivery. The conversation stays locked during the pause, which is the behavior I want: the next message of that customer should not overtake a failed one, and a dependency that is down is not hit in a tight loop. After five deliveries Service Bus moves the trigger to the dead-letter queue. Because the trigger has no payload, nothing is lost there; Phase 2 switches the conversation to handoff and Phase 6 puts an alarm on the dead-letter count.

The queue is a port with two implementations, Service Bus and an in-memory one for tests. One contract test suite runs against both, the first against Microsoft's emulator, so the tests of the API and the worker can use the in-memory queue without drifting from the real behavior.

## Alternatives rejected

A Service Bus queue without sessions, with the database lease as the only lock. One long-lived receiver instead of a connection per conversation, so it is faster (see the cost below). I kept sessions because the platform then orders and withholds a conversation without my code, and a second trigger for a busy conversation costs nothing instead of a lock attempt in Postgres. It is the alternative I would return to if the load test shows the session handshake as the bottleneck.

Azure Storage queues. Cheaper and simpler, with no sessions, no ordering and no duplicate detection.

Postgres alone as the queue (`SELECT ... FOR UPDATE SKIP LOCKED`). With the inbox already in Postgres this would work and remove one moving part. I kept a queue because the worker then scales on queue length with the platform's own scaler, the dead-letter queue comes from the platform, and the API never holds work in memory. It is the alternative I would pick on a single VPS.

Payload in the queue message. Then the queue becomes a second source of truth, a burst arrives as separate jobs, and a message that reaches the dead-letter queue has to be replayed in order.

Trusting the session lock for exclusivity. Wrong as soon as a lock is lost while a slow model call is in flight.

## Cost of this choice

Two mechanisms for one property, the session and the database lease, and I have to explain why both exist.

Accepting a session is a connection of its own in the SDK, opened and closed around every turn. I do not know yet what that costs. Phase 1 measures it and this section gets the number.

Locally the queue is Microsoft's Service Bus emulator, which needs a SQL Server container, allows ten connections in all, reads its queues from a file and caps the delivery count at ten and the duplicate window at five minutes. Its fidelity for sessions and dead-lettering is not documented, so the ordering tests of Phase 1 run against it and the lease is what the correctness argument rests on.
