# Measurements

Every number in the README comes from an entry in this file. An entry has the date, the commit, what was measured, on what hardware or environment, the result, and the command that reproduces it. A number without a command to reproduce it does not go in.

## Phase 0, 2026-11-17

No measurement. Phase 0 is investigation and design; nothing runs yet. The figures in docs/design/cost-estimate.md are estimates from published prices and assumed token counts, and are labelled as such there. They are replaced by measured values in Phases 1, 4 and 5.

## Planned entries

- Phase 1, pending: the same latency with a real model on Azure OpenAI.
- Phase 2: block rate on adversarial cases and false block rate on benign cases, for the numeric guardrail.
- Phase 3: eval metrics before and after one real prompt change, the cost of a full suite run, and quality, cost per conversation and latency for each model the subscription can deploy.
- Phase 4: cost per conversation before and after routing, model and channel separately, with the quality metrics beside them; recall and precision at k for retrieval.
- Phase 5: actual monthly cost of the deployed environment against the estimate.
- Phase 6: throughput and p95 under load; result of the chaos scenario.
