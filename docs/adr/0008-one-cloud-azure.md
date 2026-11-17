# 0008. One cloud, Azure, with the region chosen for price

Status: accepted

## Context

The system needs a place to run containers, a managed PostgreSQL with row-level security and pgvector, a queue that orders by conversation, a secret store, an identity for each workload, and a language model with tool calling. I wanted all of it in one cloud, under one identity system, so that no service holds a key for another.

The honest starting point is the account, not a comparison chart. This is a portfolio project paid from a student subscription: Azure for Students, USD 100 of credit, no payment method attached. Checked on 2026-11-17 (docs/verificado.md, docs/design/cost-estimate.md):

- The subscription is disabled when the credit runs out and has nothing to charge, so the worst case for money is zero.
- It has quota for a set of models on Azure OpenAI and Foundry, among them `gpt-5-mini`, `gpt-4.1-mini` and `o4-mini`, and none for the newest ones. A `gpt-5-mini` deployment answered a test prompt on the day.
- Anthropic's models in Foundry are sold through Azure Marketplace and the documentation excludes student and credit-only subscriptions by name. A second model vendor is not reachable from this subscription.
- Container Apps, Service Bus Standard and PostgreSQL flexible server exist in both East US 2 and Brazil South. Container Apps, Service Bus, the registry and Key Vault cost the same in both. PostgreSQL costs about twice as much in Brazil South for compute and storage, and log ingestion about 1.7 times.
- Model deployments are Global Standard, which routes a request to any region with capacity. Running the application in Brazil does not keep inference in Brazil.
- Which regions a student subscription may create resources in is not documented. Microsoft staff wrote in a community thread that it "only works in certain Azure regions".

Where the time goes: a WhatsApp message reaches the system as a webhook from Meta's servers, not from a phone in Brazil, and the reply goes back to Meta's API. A turn then spends seconds in model calls. The only paths where a Brazilian user talks to the system directly are the panel and the web chat demo.

## Decision

Everything runs on Azure: Container Apps for the three services, Azure Database for PostgreSQL flexible server, Service Bus, Key Vault, Container Registry, Azure OpenAI in Foundry for the model, Azure Monitor for logs. Each service signs in to the others with its managed identity. There is no access key in configuration except the one PostgreSQL password pair, which lives in Key Vault.

The region is East US 2, for price. If the subscription's policy does not allow it, the Terraform variable takes the cheapest region it does allow; the first step of Phase 5 is to read that policy.

The model is `gpt-5-mini` to begin with, because it has the largest quota and the lowest input price of what the subscription can deploy. That is a choice by availability, not by measurement. Phase 3 runs the golden set against every model the subscription can deploy and the default becomes whichever the numbers support.

## Alternatives rejected

AWS, which is where I first designed this: Fargate, SQS FIFO and Bedrock. The account I had for it was new, its Bedrock quota was zero for every model, and the increase request had no answer. Hosting there and calling the model on Azure would have worked, with a federated identity between the clouds, at the price of two billing accounts, two identity systems and an egress path to operate. One cloud is simpler to run and to explain.

Brazil South. Lower latency for the panel, about USD 16 more per month for the same environment, and no gain in data residency because inference is global anyway.

A second model vendor through a direct API key. It is the cheapest way to prove the provider port with two real vendors, and it needs a paid account outside this subscription. Left for Phase 3 as an option, not a dependency.

## Cost of this choice

The provider comparison the project promised is, for now, between models of one platform, not between two clouds. The port still has two implementations, Azure OpenAI and the deterministic offline model, and the adapter for a second vendor is one module away, but I have not run one.

Customer messages, names and phone numbers are processed and stored outside Brazil. The seed data is fictional, so nothing real is transferred, but a real deployment for Brazilian businesses would have to document this as an international transfer under LGPD.

A student subscription has limits I could not read in the documentation: allowed regions, vCPU quota, and whether model quota can ever grow. The documentation says free-tier subscriptions are not eligible for quota increases and does not say which tier a student subscription is. If Phase 5 finds a wall, the deployment moves to a pay-as-you-go subscription unchanged, since nothing in the Terraform depends on the offer.
