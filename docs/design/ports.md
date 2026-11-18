# Port contracts

Status: proposed in Phase 0, not implemented. The signatures below are the contract, written as Python protocols so they can be reviewed before any implementation exists.

There are two ports, because there are two places with more than one real implementation: the channel and the model provider. Tools are not a port. They are domain functions with a schema, called in process by the graph and exposed a second time through an MCP server.

## Channel

A channel has an inbound side, which is HTTP and specific to each provider, and an outbound side, which the worker calls. The graph sees neither. It receives normalized messages and produces normalized replies.

```python
class InboundMessage(BaseModel):
    channel: Literal["whatsapp", "webchat"]
    channel_account_external_id: str   # WhatsApp phone number id, or the webchat widget id
    provider_message_id: str           # the idempotency key
    sender_external_id: str            # WhatsApp business-scoped user id; webchat session id
    sender_phone: str | None           # WhatsApp omits it once the user has a username
    sender_display_name: str | None
    text: str
    sent_at: datetime                  # provider timestamp, UTC
    raw: dict[str, Any]                # stored as received


class InboundAdapter(Protocol):
    def verify(self, headers: Mapping[str, str], body: bytes) -> bool:
        """Authenticate the request over the raw bytes, before any parsing."""

    def parse(self, body: bytes) -> list[InboundMessage]:
        """One request can carry several messages. Non-message events return an empty list."""


class OutboundMessage(BaseModel):
    conversation_id: UUID
    turn_id: UUID
    seq: int
    text: str
    kind: Literal["reply", "wait_notice", "handoff_notice", "refusal"]


class SendReceipt(BaseModel):
    provider_message_id: str | None
    accepted_at: datetime


class ChannelSender(Protocol):
    async def send(self, to_external_id: str, message: OutboundMessage) -> SendReceipt:
        """Raises ChannelWindowClosed, ChannelRejected or ChannelUnavailable."""

    async def signal_activity(self, to_external_id: str, in_reply_to: str) -> None:
        """Read receipt and typing indicator where the channel has them. Best effort."""
```

Rules that hold for every adapter:

- `verify` runs on the raw body. A request that fails is answered with 401 and counted, and nothing is stored.
- The webhook handler does three things and returns: verify, insert into `inbound_events` under the unique key, enqueue the trigger. A unique violation means a redelivery and is answered with 2xx without enqueueing.
- `send` is called by the worker after the turn has committed, reading from the outbox. Only `ChannelUnavailable` is retried. The provider message id is saved on the outbox row in the same transaction that marks it sent. WhatsApp has no idempotency key for sends that I could find, so a crash between the provider accepting a message and that transaction can deliver one duplicate. I accept that window and count it.
- Inbound order is not guaranteed by the provider. Messages of a turn are ordered by provider timestamp and then by arrival.
- The error types are part of the contract because the worker reacts differently to each: a closed service window on WhatsApp is not a retry, it is a state of the conversation.

The WhatsApp adapter and the web chat adapter implement both sides. The web chat inbound is a POST from the BFF; its outbound publishes to the SSE stream of that session.

## Model provider

```python
class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]       # JSON Schema generated from the Pydantic input model


class ModelRequest(BaseModel):
    model: str                         # provider model or deployment id, chosen by the router
    system: str
    messages: list[Message]            # user, assistant and tool result turns
    tools: list[ToolSpec] = []
    tool_choice: Literal["auto", "none"] = "auto"
    output_schema: dict[str, Any] | None = None   # structured output for classify
    max_output_tokens: int
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    timeout_s: float


class Usage(BaseModel):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ModelResponse(BaseModel):
    text: str | None
    tool_calls: list[ToolCall]         # id, name, arguments already parsed as JSON
    stop_reason: Literal["end", "tool_use", "max_tokens", "refused", "filtered"]
    usage: Usage
    model: str                         # what the provider reports having served
    provider_request_id: str | None
    latency_ms: int


class ModelProvider(Protocol):
    name: str

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Raises ModelTimeout, ModelThrottled, ModelUnavailable or ModelRejected."""
```

Rules:

- The port is about one call. Routing, budget, cost accounting and tracing wrap the port; they are not inside the adapters, so they are written once.
- Every call has a timeout. `ModelThrottled` and `ModelUnavailable` are retried with backoff inside the turn deadline; `ModelRejected` (bad request, content filter) is not.
- `usage` is mandatory. A response without token counts is an adapter bug, because the cost ledger and the budget depend on it.
- The request has no temperature and no forced tool choice, on purpose. The GPT-5 reasoning models on Azure OpenAI reject `temperature` and `top_p` (see verificado.md), other current model families reject non-default sampling too, and forcing one named tool is not accepted everywhere. A contract that offered them would work on one model and fail on the next. When a node needs a fixed shape, it uses `output_schema`; reproducibility in tests comes from the fake provider and from cached responses in the eval suite, not from temperature zero.
- `reasoning_effort` is the one tuning knob in the contract, because the reasoning models expose it and it changes cost and latency by a large factor. The router sets it per node.
- Arguments of tool calls come back parsed. A provider that returns malformed JSON for arguments is normalized to a tool error the planner can see, not to an exception.
- There is no streaming method in the contract in Phase 1. Replies are validated before sending, so the customer never receives tokens as they are generated (ADR 0005). If time to first token becomes a metric I want, a stream method is added then.

Three implementations: Azure OpenAI; a deterministic offline model that the compose stack runs on when no credentials are present; and a scripted fake for tests, which fails loudly on a request it has no script for.

The real adapter is written on the vendor SDK directly instead of on LangChain chat model classes, and so would a second one be. ADR 0003 records why and what it costs.

## Embeddings

```python
class EmbeddingProvider(Protocol):
    model_id: str
    dimensions: int

    async def embed(self, texts: Sequence[str], kind: Literal["document", "query"]) -> list[list[float]]: ...
```

Embeddings are not routed per call. One embedding model is configured per deployment, its id is stored with every chunk, and changing it means ingesting again.

As built in Phase 4 the protocol is smaller: `embed(texts)` returns the vectors and the tokens used, with no document and query kinds, because the one model here does not distinguish them. An embedder also carries the distance past which a chunk is not an answer, since distances of different models are not on one scale. There are two: an Azure OpenAI deployment, and an offline one that hashes words, which is what the stack and the tests run on with no credentials.

## Tools

```python
class ToolContext(BaseModel):
    tenant_id: UUID
    conversation_id: UUID
    customer_id: UUID
    turn_id: UUID
    now: datetime                      # the turn's clock, tenant timezone applied by the tool
    idempotency_key: str               # turn_id:tool_call_seq, generated by the worker


class Tool(Protocol[InputT, OutputT]):
    name: str
    description: str
    effect: Literal["read", "write"]
    input_model: type[InputT]
    output_model: type[OutputT]

    async def run(self, ctx: ToolContext, args: InputT, session: AsyncSession) -> OutputT: ...

    def facts(self, output: OutputT) -> list[Fact]:
        """Typed values of the result that the reply is allowed to state."""
```

The tools in Phase 1:

- `list_services`, `get_business_info`: read.
- `quote(service_ids, starts_at)`: read. Returns each price and the total, so the model never adds.
- `check_availability(service_id, date, resource_id?)`: read. Returns concrete free slots.
- `list_customer_bookings`: read. Only the bookings of the customer in the context.
- `create_booking`, `reschedule_booking`, `cancel_booking`: write. Each returns either the resulting booking or a typed refusal (slot taken, outside hours, notice too short) that the planner can act on.
- `request_handoff`: write.

Rules:

- Tenant and customer are in the context, set by the worker. They are not parameters, so the model cannot ask for another customer's bookings or another tenant's schedule, whatever the conversation says.
- Arguments are validated by the input model before `run`. A validation error is returned to the planner as a tool error.
- A write tool is idempotent on the key in the context.
- `facts` is what links tools to the numeric guardrail: a tool declares which values of its result may appear in a reply, with their type.

## MCP server

The same tool objects are registered in an MCP server. The server authenticates the caller, maps the credential to one tenant, builds the context itself, and passes every write through the same gate the graph uses, so an action that needs the owner's approval in a conversation also needs it through MCP. The agent in the graph does not call tools through MCP; it calls them in process, in the same transaction as the turn.

## Trigger queue

The API and the worker see the queue through a small port, in `frontdesk/queue/port.py`. `send(trigger, deduplication_id)` enqueues a trigger and drops a repeat of the same id. `lease(wait_seconds)` takes the next conversation that has triggers waiting and that nobody else holds, or returns nothing after the wait. A lease gives the oldest trigger with `receive()`, removes it with `ack`, gives it back counting an attempt with `retry`, and ends with `release`.

Two implementations: Azure Service Bus, where the lease is a session, and an in-memory queue used by the API and worker tests. One contract suite runs against both. ADR 0001 has the reasoning and the measured cost.
