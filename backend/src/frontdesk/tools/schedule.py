"""Tools about availability."""

import datetime as dt
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.domain import schedule
from frontdesk.domain.tenants import load_tenant
from frontdesk.tools.base import Tool, ToolInput
from frontdesk.tools.context import ToolContext


class CheckAvailabilityInput(ToolInput):
    service_id: UUID = Field(description="Serviço desejado, pelo id.")
    date: dt.date = Field(description="Dia a consultar, no calendário local do estabelecimento.")
    resource_id: UUID | None = Field(
        default=None,
        description="Profissional ou quadra específica. Omita para consultar todos.",
    )


async def _check_availability(
    context: ToolContext, arguments: CheckAvailabilityInput, session: AsyncSession
) -> schedule.Availability:
    tenant = await load_tenant(session, context.tenant_id)
    return await schedule.availability(
        session,
        tenant,
        service_id=arguments.service_id,
        day=arguments.date,
        now=context.now,
        resource_id=arguments.resource_id,
    )


check_availability = Tool(
    name="check_availability",
    description=(
        "Lista os horários livres de um serviço em um dia, por profissional ou quadra. "
        "Só ofereça ao cliente horários que esta ferramenta retornou."
    ),
    effect="read",
    input_model=CheckAvailabilityInput,
    handler=_check_availability,
)
