"""Tools that read and write bookings."""

from datetime import datetime
from uuid import UUID

from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.domain import bookings
from frontdesk.domain.bookings import Requester
from frontdesk.domain.tenants import load_tenant
from frontdesk.tools.base import Tool, ToolInput
from frontdesk.tools.context import ToolContext

_LOCAL_TIME = "no horário local do estabelecimento"


class CreateBookingInput(ToolInput):
    service_id: UUID = Field(description="Serviço a agendar, pelo id.")
    resource_id: UUID = Field(description="Profissional ou quadra, pelo id.")
    starts_at: datetime = Field(description=f"Início do atendimento, {_LOCAL_TIME}.")


class ListCustomerBookingsInput(ToolInput):
    pass


class CancelBookingInput(ToolInput):
    booking_id: UUID = Field(description="Agendamento a cancelar, pelo id.")


class RescheduleBookingInput(ToolInput):
    booking_id: UUID = Field(description="Agendamento a mudar, pelo id.")
    starts_at: datetime = Field(description=f"Novo início do atendimento, {_LOCAL_TIME}.")
    resource_id: UUID | None = Field(
        default=None,
        description="Novo profissional ou quadra. Omita para manter o atual.",
    )


def _requester(context: ToolContext) -> Requester:
    return Requester(customer_id=context.customer_id, now=context.now)


async def _create_booking(
    context: ToolContext, arguments: CreateBookingInput, session: AsyncSession
) -> bookings.Booked | bookings.Refused:
    tenant = await load_tenant(session, context.tenant_id)
    return await bookings.create_booking(
        session,
        tenant,
        _requester(context),
        service_id=arguments.service_id,
        resource_id=arguments.resource_id,
        starts_at=arguments.starts_at,
        idempotency_key=context.idempotency_key,
    )


async def _list_customer_bookings(
    context: ToolContext, _arguments: ListCustomerBookingsInput, session: AsyncSession
) -> bookings.BookingList:
    tenant = await load_tenant(session, context.tenant_id)
    return await bookings.list_bookings(session, tenant, _requester(context))


async def _cancel_booking(
    context: ToolContext, arguments: CancelBookingInput, session: AsyncSession
) -> bookings.Cancelled | bookings.Refused:
    tenant = await load_tenant(session, context.tenant_id)
    return await bookings.cancel_booking(session, tenant, _requester(context), arguments.booking_id)


async def _reschedule_booking(
    context: ToolContext, arguments: RescheduleBookingInput, session: AsyncSession
) -> bookings.Rescheduled | bookings.Refused:
    tenant = await load_tenant(session, context.tenant_id)
    return await bookings.reschedule_booking(
        session,
        tenant,
        _requester(context),
        booking_id=arguments.booking_id,
        starts_at=arguments.starts_at,
        resource_id=arguments.resource_id,
    )


create_booking = Tool(
    name="create_booking",
    description=(
        "Agenda um serviço para o cliente desta conversa em um horário livre. "
        "Confirme o horário com check_availability antes."
    ),
    effect="write",
    input_model=CreateBookingInput,
    handler=_create_booking,
)

list_customer_bookings = Tool(
    name="list_customer_bookings",
    description="Lista os agendamentos futuros do cliente desta conversa.",
    effect="read",
    input_model=ListCustomerBookingsInput,
    handler=_list_customer_bookings,
)

cancel_booking = Tool(
    name="cancel_booking",
    description="Cancela um agendamento do cliente desta conversa.",
    effect="write",
    input_model=CancelBookingInput,
    handler=_cancel_booking,
)

reschedule_booking = Tool(
    name="reschedule_booking",
    description="Muda o horário, e opcionalmente o profissional ou a quadra, de um agendamento.",
    effect="write",
    input_model=RescheduleBookingInput,
    handler=_reschedule_booking,
)
