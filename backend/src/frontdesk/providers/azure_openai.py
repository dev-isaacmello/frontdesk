"""Azure OpenAI behind the provider port, on the vendor SDK (ADR 0003).

The adapter speaks Chat Completions on the v1 route, where the `model` field is the name
of the deployment. Retries are left to the caller: the client is expected to be built
with `max_retries=0`, so that retry policy lives in one place.
"""

import json
import time
from typing import Any, Literal

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageToolCall

from frontdesk.providers.port import (
    Message,
    ModelFilteredError,
    ModelRejectedError,
    ModelRequest,
    ModelResponse,
    ModelThrottledError,
    ModelTimeoutError,
    ModelUnavailableError,
    ToolCall,
    Usage,
)

type StopReason = Literal["end", "tool_use", "max_tokens", "refused", "filtered"]

# The error code of a prompt stopped by the content filter, sent with HTTP 400. A jailbreak
# attempt in a customer message is answered this way.
_FILTERED = "content_filter"

_STOP_REASONS: dict[str, StopReason] = {
    "stop": "end",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "filtered",
}


class AzureOpenAIProvider:
    name = "azure_openai"

    def __init__(self, client: AsyncOpenAI, *, reasoning_models: frozenset[str]) -> None:
        self._client = client
        self._reasoning_models = reasoning_models

    async def complete(self, request: ModelRequest) -> ModelResponse:
        started = time.perf_counter()
        try:
            completion = await self._client.chat.completions.create(
                **self._payload(request), timeout=request.timeout_s
            )
        except openai.APITimeoutError as error:
            raise ModelTimeoutError(str(error)) from error
        except openai.RateLimitError as error:
            raise ModelThrottledError(str(error)) from error
        except (openai.APIConnectionError, openai.InternalServerError) as error:
            raise ModelUnavailableError(str(error)) from error
        except openai.APIStatusError as error:
            if _was_filtered(error):
                raise ModelFilteredError(str(error)) from error
            raise ModelRejectedError(str(error)) from error
        return _response(request, completion, time.perf_counter() - started)

    def _payload(self, request: ModelRequest) -> dict[str, Any]:
        payload = _base_payload(request)
        # A model that does not reason rejects the whole request over this one field.
        if request.reasoning_effort is not None and request.model in self._reasoning_models:
            payload["reasoning_effort"] = request.reasoning_effort
        return payload


def _was_filtered(error: openai.APIStatusError) -> bool:
    """Whether the content filter stopped the prompt. The models say it in two shapes.

    The Azure OpenAI models answer with an error whose code is `content_filter`. Other
    models of the same resource answer HTTP 400 around a completion whose only choice
    finished for that reason.
    """
    if error.code == _FILTERED:
        return True
    body = error.body
    if not isinstance(body, dict):
        return False
    choices = body.get("choices")
    return (
        isinstance(choices, list)
        and bool(choices)
        and isinstance(choices[0], dict)
        and choices[0].get("finish_reason") == _FILTERED
    )


def _base_payload(request: ModelRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [
            {"role": "system", "content": request.system},
            *(_message(message) for message in request.messages),
        ],
        "max_completion_tokens": request.max_output_tokens,
    }
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in request.tools
        ]
        payload["tool_choice"] = request.tool_choice
    if request.output_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "output", "schema": request.output_schema, "strict": True},
        }
    return payload


def _message(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content}
    if message.tool_calls:
        return {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                }
                for call in message.tool_calls
            ],
        }
    return {"role": message.role, "content": message.content}


def _response(request: ModelRequest, completion: ChatCompletion, seconds: float) -> ModelResponse:
    choice = completion.choices[0]
    usage = completion.usage
    assert usage is not None, "the provider always reports usage on a completed call"
    details = usage.prompt_tokens_details
    cached = (details.cached_tokens or 0) if details is not None else 0
    return ModelResponse(
        text=choice.message.content,
        tool_calls=tuple(
            _tool_call(call)
            for call in choice.message.tool_calls or ()
            if isinstance(call, ChatCompletionMessageToolCall)
        ),
        stop_reason=(
            "refused" if choice.message.refusal else _STOP_REASONS.get(choice.finish_reason, "end")
        ),
        # The provider counts cached tokens inside prompt tokens and reasoning tokens
        # inside completion tokens. Cached input is priced apart; reasoning is output.
        usage=Usage(
            input_tokens=usage.prompt_tokens - cached,
            output_tokens=usage.completion_tokens,
            cache_read_tokens=cached,
        ),
        # The deployment that was asked for, which is what the price table is keyed on.
        model=request.model,
        provider_request_id=completion.id,
        latency_ms=round(seconds * 1000),
    )


def _tool_call(call: ChatCompletionMessageToolCall) -> ToolCall:
    try:
        arguments = json.loads(call.function.arguments)
    except json.JSONDecodeError:
        arguments = None
    if not isinstance(arguments, dict):
        # No tool declares this field, so validation turns it into an error the planner sees.
        arguments = {"unparseable_arguments": call.function.arguments}
    return ToolCall(id=call.id, name=call.function.name, arguments=arguments)
