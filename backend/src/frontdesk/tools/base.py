"""A tool is a domain function with a validated input schema and a name the model can call."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.tools.context import ToolContext


class ToolInput(BaseModel):
    """Arguments a model may send. A field that is not declared is an error, not noise."""

    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class Tool[InputT: BaseModel, OutputT: BaseModel]:
    name: str
    description: str
    effect: Literal["read", "write"]
    input_model: type[InputT]
    handler: Callable[[ToolContext, InputT, AsyncSession], Awaitable[OutputT]]

    async def run(self, context: ToolContext, arguments: InputT, session: AsyncSession) -> OutputT:
        return await self.handler(context, arguments, session)
