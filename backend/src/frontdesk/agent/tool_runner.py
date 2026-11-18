"""Runs the tool calls a model asked for, and nothing the model did not have the right to ask."""

import json
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from frontdesk import telemetry
from frontdesk.agent.turn import TurnInput
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.guardrail import Fact
from frontdesk.providers.port import Message, ToolCall
from frontdesk.tools.context import ToolContext
from frontdesk.tools.facts import facts_of
from frontdesk.tools.registry import TOOLS


@dataclass(frozen=True)
class ToolOutcome:
    message: Message
    """What the planner reads as the result of its call."""

    facts: tuple[Fact, ...] = ()
    """Every value the tool was asked about or returned, for the numeric guardrail."""

    effect: str | None = None
    """What the tool did, when it did something a reply could claim."""

    refused: str | None = None
    """Why the call never reached a tool: its name or its arguments were wrong."""


async def run_tool_call(
    sessions: SessionFactory, turn: TurnInput, call: ToolCall, sequence: int, timezone: ZoneInfo
) -> ToolOutcome:
    """Executes one call.

    `sequence` is the position of the call in the turn. It makes the idempotency key the
    same when the turn is retried, so a write that already happened is not repeated.
    """
    with telemetry.span(
        f"execute_tool {call.name}",
        {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": call.name,
            "gen_ai.tool.call.id": call.id,
        },
    ) as execution:
        outcome = await _run(sessions, turn, call, sequence, timezone)
        execution.set_attribute("frontdesk.tool.effect", outcome.effect or "none")
        if outcome.refused:
            # A call the model got wrong is an error of the call, with no exception.
            execution.set_attribute("error.type", outcome.refused)
        return outcome


async def _run(
    sessions: SessionFactory, turn: TurnInput, call: ToolCall, sequence: int, timezone: ZoneInfo
) -> ToolOutcome:
    tool = TOOLS.get(call.name)
    if tool is None:
        return ToolOutcome(_result(call, {"error": "unknown_tool"}), refused="unknown_tool")

    try:
        arguments = tool.input_model.model_validate(call.arguments)
    except ValidationError as error:
        details = json.loads(error.json(include_url=False, include_input=False))
        return ToolOutcome(
            _result(call, {"error": "invalid_arguments", "details": details}),
            refused="invalid_arguments",
        )

    context = ToolContext(
        tenant_id=turn.tenant_id,
        customer_id=turn.customer_id,
        now=turn.now,
        idempotency_key=f"{turn.turn_id}:{sequence}",
    )
    async with tenant_transaction(sessions, turn.tenant_id) as session:
        output = await tool.run(context, arguments, session)
    return ToolOutcome(
        message=Message(role="tool", tool_call_id=call.id, content=output.model_dump_json()),
        facts=(*facts_of(arguments, timezone), *facts_of(output, timezone)),
        effect=_effect(output),
    )


def _effect(output: BaseModel) -> str | None:
    status = getattr(output, "status", None)
    if status in ("booked", "cancelled", "rescheduled"):
        return str(status)
    if getattr(output, "bookings", None):
        return "listed"
    return None


def _result(call: ToolCall, payload: dict[str, Any]) -> Message:
    return Message(role="tool", tool_call_id=call.id, content=json.dumps(payload))
