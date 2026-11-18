# Cost is over budget

## What you see

One of two things, and they are different problems.

A tenant reached its monthly budget. Its usage screen in the panel says so, its conversations are answered by the economy model, and a quarter past the budget they go to a person with the reason that the spending limit was reached.

Or the whole deployment reached its cap for the day. Every tenant's conversations go to a person, with the same reason, until the day changes in UTC.

## What to check

What was spent today against the cap, and by whom this month:

```sql
select day, cost_microusd / 1e6 as usd from deployment_spend order by day desc limit 7;

select t.slug, t.monthly_budget_microusd / 1e6 as budget_usd, sum(c.cost_microusd) / 1e6 as spent_usd
from tenants t join model_calls c on c.tenant_id = t.id
where c.created_at >= date_trunc('month', now())
group by t.slug, t.monthly_budget_microusd;
```

Then whether the spending is use or a fault. A conversation on the default model costs about USD 0.0006 (docs/medicoes.md). A tenant far above its number of conversations times that is being talked to by something that is not a customer, or a turn is looping: a turn is limited to six rounds of tools, ten model calls and 120,000 tokens, so one conversation cannot spend without bound, and many conversations can.

```sql
select conversation_id, count(*) as turns, sum(blocked_drafts) as redone
from turns where tenant_id = :tenant and started_at >= now() - interval '1 day'
group by conversation_id order by turns desc limit 10;
```

## What to do

If it is abuse of the public chat, stop model calls for everyone while it is dealt with:

```
python -m frontdesk.ops model-calls off
```

If it is honest use, the limit is a decision and not an incident. A tenant's budget is the column `monthly_budget_microusd` of `tenants`, and the daily cap is `FRONTDESK_DAILY_CAP_USD` in the worker's and the API's environment. Raising either takes effect at the next turn.

## What the limits do not do

They are read when a turn starts, so turns already running finish, and the totals can pass the limit by what those turns cost. The cap counts model calls only. A WhatsApp message past the free tier costs about twelve times the model calls behind it, and nothing here caps that yet.

## Rehearsed

Locally, on 2026-11-18, with a real model: a tenant with its budget set below what it had spent got the handoff notice with no model call, and the switch turned off and on did the same for the other tenant.
