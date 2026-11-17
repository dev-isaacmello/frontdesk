# 0003. The provider port is implemented on the vendor SDKs, not on LangChain chat models

Status: accepted

## Context

The graph must not change when the provider changes, and the same eval suite has to run against more than one model and compare quality, latency and cost. Cost and budget depend on exact token usage per call.

LangGraph does not require LangChain chat models: a node is a function. LangChain's `ChatOpenAI` and its siblings are already an abstraction over providers, so using them would make my port a wrapper around a wrapper.

Checked in docs/verificado.md: Microsoft's current guidance for Azure OpenAI is the plain `OpenAI` client pointed at the `/openai/v1/` route, with no `api-version`, the deployment name as the model, and an Entra token provider in place of the key. On that route the GPT-5 reasoning models take `max_completion_tokens` and reject `temperature`. Cached tokens are reported inside prompt tokens and reasoning tokens inside completion tokens.

## Decision

The port in docs/design/ports.md has these implementations:

- Azure OpenAI: the `openai` SDK async client against the v1 route, with the SDK's own retries switched off so that retry policy lives in one place, authenticated with an API key locally and with the managed identity in Azure.
- Offline: deterministic, rule-based, for running the whole stack with no account.
- Scripted: deterministic, one script per test.

Routing, budget checks, cost recording and tracing wrap the port once.

The adapter speaks Chat Completions, not the Responses API. Microsoft recommends Responses for new work. I chose Chat Completions because it is the wire format the largest number of providers and gateways accept, which keeps the adapter useful beyond this one deployment, and because `gpt-5-mini` supports tools and strict structured output on it.

## Alternatives rejected

LangChain chat models behind the port. Less code for tool call normalization and automatic tracing in LangSmith or Langfuse. I rejected it because usage metadata, retries and timeouts become whatever each wrapper does in its current version, and because a reviewer reading the adapter learns nothing about how the provider API is used.

The `AzureOpenAI` client class with an `api-version`. It is the older route. The v1 route is generally available and removes a version string that has to be kept current.

The Responses API. It is where the provider is going, and the newest model family already refuses tools on Chat Completions unless reasoning is off. Moving to it is a rewrite of one module's payloads behind the same port, and I would do it when a model I want requires it.

## Cost of this choice

I write and test the translation of messages, tool schemas, tool calls, stop reasons and usage for each provider, one small module each, and I own their bugs. The adapter is tested against canned HTTP responses in the documented format, which proves the translation and not the provider: a real call is what Phase 3 adds. Staying on Chat Completions is a debt with a known trigger, described above.
