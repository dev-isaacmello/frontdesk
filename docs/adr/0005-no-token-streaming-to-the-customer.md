# 0005. Replies are validated before sending, so no token streaming to the customer

Status: accepted

## Context

The numeric guardrail checks the whole reply against what the tools returned. A reply that fails is regenerated once and then handed to a person. The web chat could stream tokens as the model produces them, which is what people expect from a chat demo.

## Decision

The customer receives a message only after it passed validation. The web chat uses SSE for status events (message received, checking the schedule, waiting for the owner) and for the final text. WhatsApp has no streaming, so both channels behave the same and go through the same pipeline.

## Alternatives rejected

Stream tokens and retract on failure. A wrong price that was on the screen for two seconds was still shown, and a retraction is worse than a short wait.

Stream only in the web chat, validate only in WhatsApp. The demo would then exercise a different path from the one the product is about.

Validate incrementally, sentence by sentence. Possible, but a number is often only wrong in relation to something said later, and it doubles the surface of the guardrail for a cosmetic gain.

## Cost of this choice

Perceived latency is the full generation time plus validation, and the demo feels slower than a streaming chat. I mitigate with status events and by keeping replies short, and I report end to end latency as it is.
