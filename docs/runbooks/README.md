# Runbooks

What to look at and what to do in four situations the system is built to survive (OPS-2). Each one names the signal as the code emits it, the commands that exist today, and what has and has not been rehearsed. Nothing here has been rehearsed against the Azure environment, because it has not been applied yet; the local stack is where each step was run or was not.

Queries that add up every tenant are run as the database superuser. The application role sees one tenant at a time, by design, and cannot answer them. The metrics named here exist when the stack is started with a metrics endpoint (ADR 0015), which locally is `docker compose --profile metrics`; their names are written as Prometheus shows them.

Two of the four were rehearsed by a script that breaks the local stack and checks what the customers got: `backend/scripts/chaos.py`.

- [The queue is growing](queue-growing.md)
- [The model provider is down](model-provider-down.md)
- [The webhook signature is failing](webhook-signature-failing.md)
- [Cost is over budget](cost-over-budget.md)
