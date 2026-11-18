# The queue is growing

## What you see

Customers wait longer for a reply. The age of the oldest customer message that no turn has taken yet keeps rising:

```sql
select tenant_id, count(*) as waiting, now() - min(occurred_at) as oldest
from messages
where direction = 'in' and turn_id is null
group by tenant_id;
```

A healthy system shows nothing here, or messages a few seconds old: a turn takes them after a quiet window of 1.5 seconds. On Azure the same pressure shows as the active message count of the `triggers` queue.

## What it means

One of three things. The worker is not running. The worker is running and every turn is failing and being retried. Or there are more conversations at once than the worker has pumps for: a worker leases one conversation per pump, six by default, and each lease is a connection with a handshake of about 0.8 seconds (ADR 0001).

## What to check

The worker's log, for the event of each case.

- No `worker_started` after the last deploy, or `queue_unavailable` repeating: the worker cannot reach the queue. Check its identity's role on the queue and the namespace's address.
- `turn_failed` repeating, with an `attempt` that climbs to 5: turns are failing. The `error_type` says what failed. A model error is the next runbook. A database error is the firewall rule of the database or its password.
- `lease_failed`: acknowledging or releasing a message failed, which a dropped connection to Service Bus does. It is logged and the pump goes on.
- None of these, and the waiting count is high: it is load.

## What to do

For load, raise `FRONTDESK_WORKER_CONCURRENCY` or add a replica of the worker. Two workers never run the same conversation: the queue gives a session to one of them and the lease on the conversation row refuses the other. The emulator used locally accepts ten connections in all, so on one machine six pumps is close to the ceiling.

For a worker that is down, start it. Nothing is lost while it is down: the messages are in PostgreSQL and the triggers wait in the queue, for up to an hour. A trigger older than that expires; the message it pointed at is answered when the customer writes again, because a turn takes every waiting message of its conversation.

## After it

A trigger that failed five times is in the dead-letter queue and its conversation was handed to a person, who sees it in the panel. Read the count of dead letters, and treat any number above zero as conversations to look at, not as a queue to replay.

## Not rehearsed

Adding a second worker replica against the real Service Bus, and the alarm on the dead-letter count, which does not exist yet.
