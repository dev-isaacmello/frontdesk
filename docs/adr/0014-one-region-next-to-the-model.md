# 0014. The demo runs in one region, the one the model is in

Status: accepted

## Context

The customers of the two fictional businesses are in Brazil, and Brazil South is where I would put a system for them. The student subscription does not allow it. Its one policy assignment, "Allowed resource deployment regions", lists North Central US, Chile Central, Italy North, Spain Central and South Africa North (docs/verificado.md, read on 2026-11-18). All five offer every resource type the environment needs.

The model resource already exists in North Central US, where Foundry created it.

A turn talks to the customer once in each direction and to the model three or four times, one call after the other. So the distance between the worker and the model is paid three or four times per turn, and the distance between the customer and the API once.

## Decision

Everything is created in North Central US: the apps, the database, the queue, the vault and the registry, beside the model.

## Alternatives rejected

Chile Central, the allowed region nearest to Brazil. It would shorten the one hop to the customer and lengthen every hop to the model, and the model calls are where the time of a turn goes. It is also the newest of the five, and its PostgreSQL offer already differs: no geo-redundant backup.

Two regions, with the API near the customer and the worker near the model. A second environment to pay for and a queue between continents, to save a fraction of a second on a reply that takes several.

## Cost of this choice

Every message crosses from Brazil to the United States and back. I expect that to be a small part of a reply whose model time alone is between two and eight seconds, and I have not measured it: the window of Phase 5 is where the number comes from.

Data of Brazilian customers would sit outside Brazil. The data here is fictional. For real customers this is a decision about where personal data is stored that a student subscription cannot make correctly, and the first thing to change with a subscription that allows Brazil South.
