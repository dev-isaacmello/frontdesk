# 0007. Hard policy in code, owner rules in text, and the text never wins

Status: accepted

## Context

The owner writes rules in free text and they apply on the next message. Free text in a prompt is an instruction channel, and the owner is not the only one who can put text in front of the model: the customer can too. Some limits must hold whatever either of them writes.

## Decision

The limits that must hold are code, not prompt. They run at two points. Before a tool executes, a gate checks the validated call against the policy and the tenant's sensitivity settings and returns allow, deny or needs approval. Before a reply is sent, validation checks the text: numbers against the fact ledger, no discount that is not registered, no claim outside the tenant's business.

Owner rules are stored as append-only versions, read at the start of each turn, and placed in the prompt as content the model should follow for tone and business practice. When a version is saved, one small model call compares each rule with the policy clauses and stores contradictions as findings for the panel. Enforcement does not depend on that call.

## Alternatives rejected

Putting the limits in the system prompt with strong wording. That is a request, not a limit, and it is the first thing a prompt injection test breaks.

Rejecting a rule version that contradicts the policy. The check is a model call and can be wrong in both directions; blocking the owner's save on it would make a classifier error into a product bug. Flagging is honest about what the check is.

Parsing owner rules into a structured policy. Out of scope: it turns a text box into a rule engine and an authoring UI.

## Cost of this choice

The owner can write a rule that is silently ineffective until they look at the findings, and the findings can miss a contradiction. The panel has to say clearly which rules are in force. The set of hard limits is fixed in code, so a tenant that needs a different limit needs a code change, which is the point.
