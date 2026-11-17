"""Runs the tool calls a model asked for, and nothing the model did not have the right to ask."""

import json
from typing import Any

from pydantic import ValidationError

from frontdesk.agent.turn import TurnInput
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.providers.port import Message, ToolCall
from frontdesk.tools.context import ToolContext
from frontdesk.tools.registry import TOOLS


async def run_tool_call(
    sessions: SessionFactory, turn: TurnInput, call: ToolCall, sequence: int
) -> Message:
    """Executes one call and returns the message the planner reads as its result.

    `sequence` is the position of the call in the turn. It makes the idempotency key the
    same when the turn is retried, so a write that already happened is not repeated.
    """
    tool = TOOLS.get(call.name)
    if tool is None:
        return _result(call, {"error": "unknown_tool"})

    try:
        arguments = tool.input_model.model_validate(call.arguments)
    except ValidationError as error:
        details = json.loads(error.json(include_url=False, include_input=False))
        return _result(call, {"error": "invalid_arguments", "details": details})

    context = ToolContext(
        tenant_id=turn.tenant_id,
        customer_id=turn.customer_id,
        now=turn.now,
        idempotency_key=f"{turn.turn_id}:{sequence}",
    )
    async with tenant_transaction(sessions, turn.tenant_id) as session:
        output = await tool.run(context, arguments, session)
    return Message(role="tool", tool_call_id=call.id, content=output.model_dump_json())


def _result(call: ToolCall, payload: dict[str, Any]) -> Message:
    return Message(role="tool", tool_call_id=call.id, content=json.dumps(payload))
