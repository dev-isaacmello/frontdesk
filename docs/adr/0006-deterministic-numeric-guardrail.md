# 0006. Numeric guardrail as a deterministic, isolated module with typed facts

Status: accepted

## Context

The failure that costs a small business money is a wrong number said with confidence: a price, a time, a date. A second model asked to check the first one has the same failure mode and adds cost and latency to every reply.

## Decision

Every reply is checked by code before it is sent. The turn keeps a ledger of typed facts (money, time of day, date, duration, count) with their origin. An extractor reads the same types from the pt-BR reply, including written-out numbers and relative dates. A value passes when the ledger has the same type and value from an origin allowed for that type. Prices, availability and booking times must come from a tool result of the same turn. Anything the extractor cannot type blocks the reply.

The module depends on nothing else in the project. Tools feed it through a `facts` method; the graph calls it in one node.

## Alternatives rejected

A model as judge on every reply. Non-deterministic, costs a call per message, and cannot be property tested.

Numbers only through templates, with the model choosing slots and code rendering the values. This removes the problem by construction and I may come back to it if the measured false block rate is bad. I did not start there because it makes replies stiff and moves the difficulty to slot selection, which fails silently instead of loudly.

Checking untyped numbers. Simpler extractor, but "30" as minutes would validate "30" as reais.

The rule exactly as first written, tool results as the only origin. A reply that repeats a number from the knowledge base, from the owner's rules or from the customer's own message would be blocked. I split origins by type instead.

## Cost of this choice

The extractor for pt-BR number and date expressions is the hard part and will have gaps; a gap is a false block, which ends in a handoff a person has to pick up. The check does not know which entity a number belongs to, so a correct price next to the wrong service passes. Both are measured in Phase 2 and published: block rate on adversarial cases next to false block rate on benign ones.

## Measured in Phase 2

On a labelled set of 86 replies the checks blocked 40 of 46 adversarial replies and 2 of 40 benign ones (docs/medicoes.md). Three of the six misses are the limit named above, a right value next to the wrong thing. The other three come from letting the opening hours vouch for weekdays, which is mine to fix. The first block is not a handoff: the draft goes back to the planner once with the value named.
