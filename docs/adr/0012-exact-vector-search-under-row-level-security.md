# 0012. The knowledge base is searched exactly, under row-level security, with no approximate index

Status: accepted

## Context

Each tenant has things its customers ask that are neither in the catalog nor in the schedule: the address, whether there is parking, how late a customer may arrive. The owner knows them and the agent has to answer them without inventing.

The texts of every tenant live in one table. pgvector's approximate indexes are built over the whole table, and its documentation says of them that "filtering is applied after the index is scanned" (docs/verificado.md). Two things follow for a shared table. A filtered query can return fewer rows than it asked for, because the nearest neighbours in the index belonged to someone else. And what another tenant stored changes which of my rows the index reaches, so one tenant's data affects another's recall. The documentation recommends partitioning or separate tables for that reason.

A sequential scan has neither problem. Row-level security removes the other tenants' rows before anything is ordered, and the distance is computed over what is left.

## Decision

`kb_chunks` is one table with the same forced policy as every other table that holds a tenant, a `vector(1536)` column and no vector index. A search runs inside the tenant's transaction and orders the rows the policy lets through by cosine distance to the question, keeping at most three that are closer than a threshold.

A chunk stores the name of the model that embedded it, and a search only compares vectors of the model it was asked with. The threshold belongs to the embedder, because distances of different models are not on one scale.

Retrieval is a node of the graph between `classify` and `plan`. It embeds the customer's message, records the call in the ledger, shows what it found to the planner, and adds the values in it to the list the reply is checked against, with their own origin. If there is no embedder or the embedding call fails, the turn goes on with nothing retrieved.

## Alternatives rejected

An HNSW index on a table partitioned by tenant. It is what I would move to, and it is the documented way to keep an approximate index from mixing tenants. It adds a partition per tenant to create and migrate, for a table that today has eight rows per tenant.

A separate vector store such as Azure AI Search. It would be a second place where tenant isolation has to hold and be tested, and a monthly cost, to search a few dozen short texts.

No retrieval at all: the whole knowledge base in the planner's prompt. With eight entries per tenant this works and I measured nothing that says retrieval is cheaper at this size. I built retrieval because the base grows with use while the prompt should not, and because the claim worth testing is that a search for one tenant cannot return another's text when the application asks for it.

## Cost of this choice

An exact scan reads every chunk of the tenant on every turn. That is nothing at tens of rows and I have not measured where it stops being nothing. When a tenant has thousands of chunks the partitioned index above is the change to make.

The threshold was chosen on 30 questions that I wrote (docs/medicoes.md). At the value that finds every answer, the search still returns something for four of the six questions the base has no answer to, such as a greeting. The planner then reads chunks it does not need, which costs tokens and is a chance to be distracted.

The embedding call is on the path of every in-scope turn.

A price written in the knowledge base cannot be stated by the agent. Money is accepted from tools only (ADR 0006), and I kept that rule here instead of opening a second source of prices.

There is no ingestion. An entry is a title and a short text, embedded whole, with no chunking and no document upload, and the panel has no screen to edit the base yet: the two demo tenants get theirs from the seed.
