"""The Azure OpenAI adapter: translation to and from the provider's wire format.

This is the one place where the provider is replaced by canned HTTP responses. The
payloads follow the Chat Completions format documented for the v1 route.
"""

import json
from typing import Any

import httpx2 as httpx
import pytest
from openai import AsyncOpenAI

from frontdesk.providers.azure_openai import AzureOpenAIProvider
from frontdesk.providers.port import (
    Message,
    ModelRejectedError,
    ModelRequest,
    ModelThrottledError,
    ModelTimeoutError,
    ModelUnavailableError,
    ToolCall,
    ToolSpec,
)

QUOTE = ToolSpec(
    name="quote",
    description="Informa o preço de um serviço.",
    input_schema={"type": "object", "properties": {"service_id": {"type": "string"}}},
)


def completion(message: dict[str, Any], finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "id": "chatcmpl-123",
        "object": "chat.completion",
        "created": 1794996000,
        "model": "gpt-5-mini-2025-08-07",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": 1200,
            "completion_tokens": 90,
            "total_tokens": 1290,
            "prompt_tokens_details": {"cached_tokens": 1000},
            "completion_tokens_details": {"reasoning_tokens": 64},
        },
    }


class Recorder:
    """An HTTP transport that answers with a canned response and keeps what was sent."""

    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body or completion({"role": "assistant", "content": "ok"})
        self.sent: dict[str, Any] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.sent = json.loads(request.content)
        self.url = str(request.url)
        return httpx.Response(self.status, json=self.body, request=request)


def provider(transport: Any) -> AzureOpenAIProvider:
    client = AsyncOpenAI(
        base_url="https://frontdesk.openai.azure.com/openai/v1/",
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
    )
    return AzureOpenAIProvider(client)


def request(**overrides: Any) -> ModelRequest:
    fields: dict[str, Any] = {
        "model": "gpt-5-mini",
        "system": "Você é o atendente.",
        "messages": (Message(role="user", content="quanto custa o corte?"),),
        "max_output_tokens": 1024,
        "timeout_s": 30,
    }
    return ModelRequest(**{**fields, **overrides})


async def test_a_request_names_the_deployment_and_carries_no_sampling_parameter() -> None:
    recorder = Recorder()

    await provider(recorder).complete(request(reasoning_effort="low"))

    assert recorder.url == "https://frontdesk.openai.azure.com/openai/v1/chat/completions"
    assert recorder.sent["model"] == "gpt-5-mini"
    assert recorder.sent["max_completion_tokens"] == 1024
    assert recorder.sent["reasoning_effort"] == "low"
    assert recorder.sent["messages"] == [
        {"role": "system", "content": "Você é o atendente."},
        {"role": "user", "content": "quanto custa o corte?"},
    ]
    assert "temperature" not in recorder.sent
    assert "tools" not in recorder.sent


async def test_tools_and_the_tool_exchange_are_translated() -> None:
    recorder = Recorder()
    call = ToolCall(id="call_1", name="quote", arguments={"service_id": "abc"})
    messages = (
        Message(role="user", content="quanto custa o corte?"),
        Message(role="assistant", tool_calls=(call,)),
        Message(role="tool", tool_call_id="call_1", content='{"total_cents": 4500}'),
    )

    await provider(recorder).complete(request(messages=messages, tools=(QUOTE,)))

    assert recorder.sent["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "quote",
                "description": "Informa o preço de um serviço.",
                "parameters": QUOTE.input_schema,
            },
        }
    ]
    assert recorder.sent["tool_choice"] == "auto"
    assert recorder.sent["messages"][2:] == [
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "quote", "arguments": '{"service_id": "abc"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"total_cents": 4500}'},
    ]


async def test_a_text_answer_comes_back_with_usage_split_by_cache() -> None:
    answer = completion({"role": "assistant", "content": "O corte sai por R$ 45,00."})

    response = await provider(Recorder(body=answer)).complete(request())

    assert response.text == "O corte sai por R$ 45,00."
    assert response.tool_calls == ()
    assert response.stop_reason == "end"
    # 1,200 prompt tokens of which 1,000 were read from cache; reasoning counts as output.
    assert response.usage.input_tokens == 200
    assert response.usage.cache_read_tokens == 1000
    assert response.usage.output_tokens == 90
    assert response.model == "gpt-5-mini"
    assert response.provider_request_id == "chatcmpl-123"


async def test_a_tool_call_comes_back_with_parsed_arguments() -> None:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_9",
                "type": "function",
                "function": {"name": "quote", "arguments": '{"service_id": "abc"}'},
            }
        ],
    }

    response = await provider(Recorder(body=completion(message, "tool_calls"))).complete(
        request(tools=(QUOTE,))
    )

    assert response.text is None
    assert response.stop_reason == "tool_use"
    assert response.tool_calls == (
        ToolCall(id="call_9", name="quote", arguments={"service_id": "abc"}),
    )


async def test_arguments_that_are_not_json_reach_the_planner_as_a_tool_error() -> None:
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "call_9", "type": "function", "function": {"name": "quote", "arguments": "{"}}
        ],
    }

    response = await provider(Recorder(body=completion(message, "tool_calls"))).complete(
        request(tools=(QUOTE,))
    )

    [call] = response.tool_calls
    assert call.arguments == {"unparseable_arguments": "{"}


async def test_a_schema_is_sent_as_strict_structured_output() -> None:
    recorder = Recorder()
    schema = {
        "type": "object",
        "properties": {"in_scope": {"type": "boolean"}},
        "required": ["in_scope"],
        "additionalProperties": False,
    }

    await provider(recorder).complete(request(output_schema=schema))

    assert recorder.sent["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "output", "schema": schema, "strict": True},
    }


async def test_a_refusal_of_structured_output_is_reported_as_refused() -> None:
    message = {"role": "assistant", "content": None, "refusal": "Não posso ajudar com isso."}

    response = await provider(Recorder(body=completion(message))).complete(request())

    assert response.stop_reason == "refused"
    assert response.text is None


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        ("stop", "end"),
        ("tool_calls", "tool_use"),
        ("length", "max_tokens"),
        ("content_filter", "filtered"),
    ],
)
async def test_finish_reasons_map_to_the_port(finish_reason: str, expected: str) -> None:
    body = completion({"role": "assistant", "content": "…"}, finish_reason)

    response = await provider(Recorder(body=body)).complete(request())

    assert response.stop_reason == expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, ModelThrottledError),
        (500, ModelUnavailableError),
        (503, ModelUnavailableError),
        (400, ModelRejectedError),
        (404, ModelRejectedError),
    ],
)
async def test_http_failures_map_to_the_port_errors(status: int, expected: type[Exception]) -> None:
    failing = Recorder(status=status, body={"error": {"code": "x", "message": "x"}})

    with pytest.raises(expected):
        await provider(failing).complete(request())


async def test_a_timeout_and_a_dropped_connection_map_to_the_port_errors() -> None:
    def times_out(http_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=http_request)

    def drops(http_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=http_request)

    with pytest.raises(ModelTimeoutError):
        await provider(times_out).complete(request())
    with pytest.raises(ModelUnavailableError):
        await provider(drops).complete(request())
