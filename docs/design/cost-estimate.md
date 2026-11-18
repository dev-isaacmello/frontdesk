# Cost estimate

Status: estimate made before any hosting resource exists. The only thing created so far is one model deployment, which costs nothing until it is called. No resource is created and no `terraform apply` runs without explicit approval of that command.

Prices were read on 2026-11-17 from the Azure Retail Prices API, `https://prices.azure.com/api/retail/prices`, filtered by service and region, because the pricing pages render their tables with JavaScript. All figures are USD retail. docs/verificado.md has the meters and the pages.

## Who pays, and the most it can cost

The subscription is Azure for Students: USD 100 of credit until 2027-11-17 and no payment method attached. When the credit ends the subscription is disabled, so it cannot charge anything. The most this project can cost in real money on Azure is zero.

The credit is still a budget. I keep model tokens for development and evaluation under USD 5 of it, enforced by the eval runner, which refuses to start a run whose estimate passes what is left. At the measured cost of a simple turn on `gpt-5-mini` that is about 4,900 turns. The infrastructure window has its own line further down.

WhatsApp: the test number, its five recipients and the messages it sends are free.

What the subscription lets me create is partly unknown. Its allowed regions and compute quotas are not documented, and the first step of Phase 5 is to read its policy before planning anything.

## The environment being priced

One environment in East US 2: three container apps (API, worker, panel) at 0.25 vCPU and 0.5 GiB each on the Container Apps consumption plan; one Azure Database for PostgreSQL flexible server, Burstable B1ms, with 32 GiB of storage; one Service Bus namespace on the Standard tier with one session queue; a Basic container registry; Key Vault; Log Analytics. No virtual network, by ADR 0010.

## A window of 72 hours, everything always on

- Container Apps: 0.43. Three apps for 72 hours use 194,400 vCPU-seconds and 388,800 GiB-seconds. The monthly free grant covers 180,000 and 360,000, and the rest is billed at 0.000024 per vCPU-second and 0.000003 per GiB-second. Without the grant it would be 5.83.
- PostgreSQL B1ms: 1.22, at 0.017 per hour. Storage: 0.36, at 0.115 per GiB-month.
- Service Bus Standard: 0.97, at 0.013441 per hour. Operations are free up to 13 million per month.
- Container Registry Basic: 0.50, at 0.1666 per day.
- Log Analytics: 0.00 under 5 GB. Key Vault: under 0.01.
- Total: 3.48.

This is the plan: apply, measure for a few days, record the numbers, destroy.

## A month, always on

- Container Apps: 53.73 at the active rate, with the grant covering about 9% of the month. If the apps qualify for the idle rate while no request is in flight, 16.12; whether a queue worker qualifies is not documented, so I plan on the higher figure.
- PostgreSQL B1ms: 12.41. Storage: 3.68.
- Service Bus Standard: 9.81.
- Container Registry Basic: 5.07.
- Log Analytics and Key Vault: about 0.
- Total: 84.70.

## A month, scaled to zero when idle

The API and the panel scale to zero replicas and the worker scales on the queue. At 2% of active time the three apps use 39,420 vCPU-seconds and 78,840 GiB-seconds, all inside the free grant. The grant covers these three apps up to about 9% of active time each, and the five-minute cool-down after the last request counts as active.

- Container Apps: 0.00.
- PostgreSQL, Service Bus, registry: 12.41 + 3.68 + 9.81 + 5.07.
- Total: 30.97.

What is left is the database and the queue, which do not scale to zero. A stopped PostgreSQL server pays for storage only and starts again by itself after seven days. The students offer lists twelve months of B1ms and 32 GB free; I have not confirmed that it applies to this subscription and the figures above do not count on it.

## The same environment in Brazil South

Container Apps, Service Bus, the registry and Key Vault cost the same. PostgreSQL B1ms is 0.035 per hour and its storage 0.2185 per GiB-month, about twice East US 2. Log ingestion past the free 5 GB is 4.60 per GB against 2.76. The 72-hour window costs 5.11 and the always-on month 101.15. ADR 0008 has why I do not use this region.

## What a virtual network would add

A Container Apps environment in its own virtual network is billed a standard load balancer and one or two standard public addresses, and the private database needs a DNS zone: about 0.035 per hour, 2.52 for the window and 25.55 for a month. ADR 0010 has why the demo does without it and what it gives up.

## Model

`gpt-5-mini` on Global Standard: 0.25 per million input tokens, 0.025 cached, 2.00 per million output tokens.

Measured on 2026-11-17 over twenty turns of one simple question (docs/medicoes.md): 3.5 model calls per turn, 2,648 input tokens of which 410 came from the provider's cache, 221 output tokens, and 1,013 micro-USD, which is a tenth of a cent per turn. My estimate before any call was 10,700 input tokens and 0.0038 per turn, about four times too high. A booking conversation makes more calls per turn and I have not averaged one yet; Phase 3 does that from the ledger, per model.

At the measured cost, USD 5 of credit is about 4,900 turns.

For comparison at list price, `gpt-4.1-mini` is 0.40 input, 0.10 cached and 1.60 output. It does not reason, so its output count is the visible answer. Which of the two is cheaper per turn depends on how much the first one reasons, and that is a measurement, not a guess.

Embeddings for retrieval in Phase 4: `text-embedding-3-small` at 0.02 per million tokens.

## Channel

WhatsApp service messages have cost money again since 2026-10-01: 1,000 free per number per month, then BRL 0.035 each. Past the free tier one reply costs more than the model calls behind it at the estimate above. The ledger records channel cost beside model cost for that reason.

## What this estimate does not know

Whether the student subscription can create each of these resources, and where. Whether the Container Apps free grant and the free PostgreSQL year apply to it. How many tokens a real turn uses. The egress volume, which I expect to be far under the free allowance and have not priced. Each of these is settled by the measured window in Phase 5, whose actual cost goes into docs/medicoes.md beside this estimate.
