# 0010. Public endpoints behind identity and a firewall, not a private network

Status: accepted

## Context

Only the API and the panel need to be reachable from the internet. The database, the queue, the vault and the model do not. On Azure the way to make them unreachable is a virtual network: the Container Apps environment in a subnet of its own, PostgreSQL in a delegated subnet with a private DNS zone, private endpoints for the rest.

What that costs, from the documentation and the Retail Prices API on 2026-11-17 (docs/design/cost-estimate.md):

- A Container Apps environment in a custom virtual network is billed one standard load balancer and one standard public address for egress, plus one more for ingress when it is external. With the private DNS zone that is about USD 25.55 per month, close to the whole always-on database.
- PostgreSQL flexible server chooses public or private access when the server is created.

Without a virtual network, each service has a public endpoint and its own gate:

- Service Bus, Key Vault and Azure OpenAI accept Entra ID tokens from an identity that holds the right role. On the model resource the documentation describes switching key authentication off; for Service Bus I expect the same and will confirm it when the Terraform is written.
- PostgreSQL has a firewall of IPv4 rules and requires TLS. Its option "allow public access from Azure services" admits connections from any Azure subscription, other customers included, so it is not a network boundary.
- The outbound addresses of a Container Apps environment "might change over time".

## Decision

The demo environment has no virtual network. Service Bus, Key Vault and Azure OpenAI are reached over their public endpoints with managed identities, with key authentication disabled wherever the service allows it. PostgreSQL has public access with a firewall rule for the environment's current outbound addresses and nothing else, TLS required, and the runtime role's password read from Key Vault.

The Terraform module takes a variable that switches the environment to a virtual network with PostgreSQL on private access. That is what I would use for an environment that holds real customer data.

## Alternatives rejected

A virtual network by default. Correct for production and the second most expensive line of the demo, for a window of a few days with fictional data.

"Allow public access from Azure services" on PostgreSQL. One checkbox and no rule to maintain, and it opens the server to every tenant of the cloud. The firewall rule on the environment's addresses is narrower and costs a rule to update.

Entra ID authentication for PostgreSQL instead of a password. It removes the last secret, and I want it. The token for the database expires and has to be refreshed inside the connection pool, and migrations run as a different role than the application. I left it out of Phase 5 to keep the first deployment small; it is the first change I would make after it.

## Cost of this choice

The database listens on the internet. What stands in front of it is a firewall rule, TLS and a password, which is weaker than not being routable at all. If the environment's outbound address changes, the application loses the database until the rule is updated; the API's health check and the queue's age are how I find out, and that failure is a candidate for the chaos scenario in Phase 6.

Identity replaces network position as the control, so a role assignment that is too wide is the mistake that matters. Each identity gets the narrowest role there is: send on the queue for the API, receive for the worker, read on the secrets it uses, and the inference role on the model resource.

## As built

The first apply, on 2026-11-18, undid one line of the decision. Without a virtual network the environment does not leave through an address of its own. It leaves through 181, scattered over twenty-one address blocks, from a pool the region shares between customers. The rule I had chosen as the narrow one was therefore 181 rules, which PostgreSQL creates one at a time at about a minute each, three hours in all, to admit a set of addresses that other customers' apps use too. It would have looked like a boundary and been none.

So the database has the rule I rejected above, access from any Azure service, and the Terraform says so where the rule is. The internet outside Azure is still refused. Inside Azure what protects the database is TLS and the passwords of its two roles, generated and kept in the vault. That is what the estimate's cheapest line buys, and it is the first thing I would pay to change: a virtual network with the database on private access, which the cost estimate puts at about USD 0.035 per hour. The variable that switches the module to it, which the decision above promises, does not exist.

The Service Bus namespace was created with local authentication disabled, as expected, so it accepts no connection string.

