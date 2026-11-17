"""The contract between the graph and a model provider (docs/design/ports.md)."""

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict


class _Value(BaseModel):
    model_config = ConfigDict(frozen=True)


class ToolSpec(_Value):
    name: str
    description: str
    input_schema: dict[str, Any]


class ToolCall(_Value):
    id: str
    name: str
    arguments: dict[str, Any]


class Message(_Value):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


class ModelRequest(_Value):
    model: str
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    tool_choice: Literal["auto", "none"] = "auto"
    output_schema: dict[str, Any] | None = None
    max_output_tokens: int
    reasoning_effort: Literal["low", "medium", "high"] | None = None
    timeout_s: float


class Usage(_Value):
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ModelResponse(_Value):
    text: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    stop_reason: Literal["end", "tool_use", "max_tokens", "refused", "filtered"]
    usage: Usage
    model: str
    provider_request_id: str | None = None
    latency_ms: int


class ModelError(Exception):
    """A model call that did not produce a response."""


class ModelTimeoutError(ModelError):
    """The provider did not answer within the request's timeout. Worth retrying."""


class ModelThrottledError(ModelError):
    """The provider refused the call because of a rate or quota limit. Worth retrying later."""


class ModelUnavailableError(ModelError):
    """The provider failed or could not be reached. Worth retrying."""


class ModelRejectedError(ModelError):
    """The provider refused this request as it is. Retrying the same request will not help."""


class ModelProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def complete(self, request: ModelRequest) -> ModelResponse: ...
