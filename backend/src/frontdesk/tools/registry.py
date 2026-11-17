"""The tools the agent can call, by name."""

from typing import Any

from frontdesk.providers.port import ToolSpec
from frontdesk.tools.base import Tool
from frontdesk.tools.bookings import (
    cancel_booking,
    create_booking,
    list_customer_bookings,
    reschedule_booking,
)
from frontdesk.tools.catalog import list_services, quote
from frontdesk.tools.schedule import check_availability

type AnyTool = Tool[Any, Any]

_ALL: tuple[AnyTool, ...] = (
    list_services,
    quote,
    check_availability,
    create_booking,
    list_customer_bookings,
    cancel_booking,
    reschedule_booking,
)

TOOLS: dict[str, AnyTool] = {tool.name: tool for tool in _ALL}

TOOL_SPECS: tuple[ToolSpec, ...] = tuple(
    ToolSpec(
        name=tool.name,
        description=tool.description,
        input_schema=tool.input_model.model_json_schema(),
    )
    for tool in _ALL
)
