"""A model that answers exactly what a test wrote for it, in order."""

from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from frontdesk.providers.port import ModelRequest, ModelResponse, ToolCall, Usage

_MODEL = "scripted"
_USAGE = Usage(input_tokens=100, output_tokens=20)


class ScriptExhaustedError(AssertionError):
    """The code under test made a model call the script did not provide for."""


class ScriptedProvider:
    name = "scripted"

    def __init__(self, script: Iterable[ModelResponse]) -> None:
        self._script = list(script)
        self.requests: list[ModelRequest] = []

    async def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if not self._script:
            raise ScriptExhaustedError(f"no scripted answer for model call {len(self.requests)}")
        return self._script.pop(0)


def says(text: str) -> ModelResponse:
    return ModelResponse(text=text, stop_reason="end", usage=_USAGE, model=_MODEL, latency_ms=0)


def calls(tool: str, arguments: dict[str, Any]) -> ModelResponse:
    call = ToolCall(id=f"call_{uuid4().hex[:12]}", name=tool, arguments=arguments)
    return ModelResponse(
        tool_calls=(call,), stop_reason="tool_use", usage=_USAGE, model=_MODEL, latency_ms=0
    )
