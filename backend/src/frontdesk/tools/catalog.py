"""Tools about services and prices."""

from datetime import datetime
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.domain import catalog
from frontdesk.domain.clock import to_local
from frontdesk.domain.tenants import load_tenant, timezone_of
from frontdesk.tools.base import Tool, ToolInput
from frontdesk.tools.context import ToolContext


class ListServicesInput(ToolInput):
    pass


class QuoteInput(ToolInput):
    service_ids: list[UUID] = Field(description="Serviços a orçar, pelo id.", min_length=1)
    starts_at: datetime = Field(
        description="Data e hora do atendimento, no horário local do estabelecimento."
    )


async def _list_services(
    _context: ToolContext, _arguments: ListServicesInput, session: AsyncSession
) -> catalog.ServiceList:
    return catalog.ServiceList(services=await catalog.list_services(session))


async def _quote(
    context: ToolContext, arguments: QuoteInput, session: AsyncSession
) -> catalog.Quote:
    tenant = await load_tenant(session, context.tenant_id)
    at = to_local(arguments.starts_at, timezone_of(tenant)).time()
    return await catalog.quote(session, arguments.service_ids, at)


list_services = Tool(
    name="list_services",
    description="Lista os serviços do estabelecimento com duração e preço por faixa de horário.",
    effect="read",
    input_model=ListServicesInput,
    handler=_list_services,
)

quote = Tool(
    name="quote",
    description=(
        "Informa o preço de um ou mais serviços em uma data e hora, com o total somado. "
        "Use sempre que for dizer um preço ou um total."
    ),
    effect="read",
    input_model=QuoteInput,
    handler=_quote,
)
