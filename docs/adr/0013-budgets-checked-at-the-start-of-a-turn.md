# 0013. Budgets are checked at the start of a turn, from the ledger

Status: accepted

## Context

Three limits on what the models may cost have to hold without anyone watching. A tenant has a monthly budget, past which it is served by a cheaper model and then only by a person. The whole deployment has a daily cap, which is what protects a demo that anyone can talk to. And an operator needs a way to stop model calls by hand.

Every model call is already in `model_calls` with its cost (CST-1). The application role reads that table under row-level security, so it can add up one tenant and can never add up all of them.

## Decision

Which model answers is a pure function of three things: the node, the tenant's plan and the tenant's level against its budget. The level is computed when a turn loads its context, from the sum of the tenant's calls since the first day of the month on the tenant's own clock. At the budget the level is economy and every call goes to the economy model. At one and a quarter times the budget it is exhausted: no model is called and the conversation goes to a person with the reason recorded.

The daily total of the deployment is one row per day in a table that has no tenant column. The ledger adds to it in the same transaction that records a call. A turn reads it at its start, and past the cap the turn goes to a person the same way.

The manual switch is a row in `system_flags`. The application role can read it and cannot change it. `python -m frontdesk.ops model-calls off` flips it as the owner role, and from the next turn on nothing calls a model.

The review of the owner's rules is the one model call outside a turn. It obeys the same three limits, and when it may not run the rules are saved with only the findings the code makes by itself.

## Alternatives rejected

Reserving the cost before each call. It would make the limits exact, and it needs an estimate of a call's cost before the call and a release when the estimate was wrong. The overshoot it prevents is bounded and small here.

Counters in a cache. There is no cache in this system and the ledger already has the truth. A counter that disagrees with the ledger is a second number to explain.

Relying on the provider's limits alone. The deployment's tokens-per-minute quota and the subscription's credit are the ceilings that hold even if this code is wrong, and I keep them. They know nothing about tenants and they fail a request instead of handing a conversation to a person.

## Cost of this choice

The limits are checked when a turn starts and not before each call, so turns already running finish. A tenant can pass its budget, and the deployment its cap, by what the turns in flight cost: at most the worker's concurrency times the token limit of a turn.

The row of the day is written by every model call of every tenant. It is one short update inside a transaction that was already open, and it is also a row that every worker contends for. The load test of Phase 6 looked: at up to 5.8 turns per second, a sample once a second found a session waiting for a lock in 7 of 260, never more than 3 at once. It is contention that exists and limits nothing at this size.

The day of the cap is the database's day, which is UTC, not a day in São Paulo.

The switch needs database access as the owner role. There is no screen for it, on purpose: it is an operator's act and not something a tenant's owner can reach.

The sum of the month runs once per turn. It has an index on tenant and time, and it still grows with the month.
