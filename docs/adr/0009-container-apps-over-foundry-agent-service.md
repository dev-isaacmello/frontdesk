# 0009. The worker runs on Azure Container Apps, not on Foundry Agent Service

Status: accepted

## Context

Microsoft Foundry has a managed platform for agents. Its hosted agents take my own code as a container image, run each session in an isolated sandbox between 0.5 vCPU with 1 GiB and 2 vCPU with 4 GiB, and expose it through the Responses or Invocations protocol. Billing is the model calls plus the CPU and memory of the active sessions. The idle timeout of a session is 15 minutes by default. Authentication is Entra ID only. (docs/verificado.md)

My worker is a queue consumer. A turn is short, all state is in Postgres, and the agent does not execute code or browse.

Azure Container Apps on the consumption plan bills per second of vCPU and memory, scales a revision to zero replicas, and scales on the length of a Service Bus queue through a KEDA rule that authenticates with a managed identity. Ingress with TLS is part of the environment, with no load balancer or public address to create. It also runs jobs, which is what the database migration needs.

## Decision

The API, the worker and the panel are three container apps in one environment. The worker has no ingress and scales on the trigger queue, from zero. The database setup is a manually started job. Foundry Agent Service is not used in this project.

## What Agent Service would have given

Isolation per session at the sandbox level, which matters for agents that run code or hold credentials per user. Mine does neither; isolation between tenants is in the database.

Managed conversation state and a managed endpoint. I already need the conversation in Postgres for the panel and for row-level security, so a second store would be a second source of truth.

## What it would have cost

A protocol in front of the agent that is not a queue: something would have to stand between Service Bus and the hosted agent, and the per-conversation ordering would then depend on that bridge. A session lifecycle that does not match a stateless turn. A local setup that no longer mirrors production, because there is no Agent Service to run in docker compose, and the project promises one command and no cloud account.

## Alternatives rejected

Azure Kubernetes Service. More control than three small services need, a control plane to operate, and out of scope by the brief.

App Service. Fine for the API and the panel, and with no scaling on queue length for the worker without adding Functions beside it.

Azure Functions with a Service Bus trigger for the worker. It would remove my receive loop. I kept a plain process because the same image then runs the API, the worker and the migration, locally and in Azure, and the loop is fifty lines I can test.

## Cost of this choice

Scaling the worker from zero adds the start of a container to the first message after an idle period; the scaler polls every 30 seconds by the documentation. For the measured window the worker keeps one replica so that the latency numbers are not about cold starts, and the estimate prices both.

Requests through Container Apps ingress time out at 240 seconds. The web chat's event stream is a long response, and whether a stream that keeps sending data is cut at that mark is not documented. The browser already reconnects with the id of the last event it saw, so the worst case is a reconnect every four minutes; Phase 5 measures which it is.

I could not confirm that the queue-length scaler counts messages held in locked sessions the way it counts free ones. If it does not, the worker scales late under load, and the load test in Phase 6 is where that would show.
