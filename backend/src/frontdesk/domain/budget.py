"""CST-3 and CST-5: what a tenant may still spend this month, and the deployment today."""

from datetime import datetime
from typing import Literal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import ModelCall, Tenant
from frontdesk.domain.clock import to_local
from frontdesk.domain.tenants import timezone_of

type Level = Literal["normal", "economy", "exhausted"]

_EXHAUSTED_AT = 1.25
"""Past the budget the tenant is served by the cheaper model; past this multiple of it,
by a person only."""


class ModelCallsClosedError(RuntimeError):
    """A model call outside a turn was not made: the budget or the deployment does not allow it."""


async def may_call_model(
    session: AsyncSession, tenant: Tenant, now: datetime, daily_cap_microusd: int | None
) -> Level | None:
    """The tenant's level when a model may be called for it now, or None when none may."""
    level = await tenant_level(session, tenant, now)
    if level == "exhausted" or not await deployment_open(session, daily_cap_microusd):
        return None
    return level


async def tenant_level(session: AsyncSession, tenant: Tenant, now: datetime) -> Level:
    """Where the tenant stands against its budget for the calendar month, on its own clock."""
    if tenant.monthly_budget_microusd is None:
        return "normal"
    month_start = to_local(now, timezone_of(tenant)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    spent = int(
        await session.scalar(
            select(func.coalesce(func.sum(ModelCall.cost_microusd), 0)).where(
                ModelCall.tenant_id == tenant.id, ModelCall.created_at >= month_start
            )
        )
        or 0
    )
    budget = tenant.monthly_budget_microusd
    if spent >= budget * _EXHAUSTED_AT:
        return "exhausted"
    return "economy" if spent >= budget else "normal"


async def deployment_open(session: AsyncSession, daily_cap_microusd: int | None) -> bool:
    """Whether model calls may be made now: the switch is on and today's cap is not reached."""
    enabled = await session.scalar(
        text("select enabled from system_flags where name = 'model_calls'")
    )
    if enabled is False:
        return False
    if daily_cap_microusd is None:
        return True
    spent = await session.scalar(
        text("select cost_microusd from deployment_spend where day = current_date")
    )
    return (spent or 0) < daily_cap_microusd


async def add_to_today(session: AsyncSession, cost_microusd: int) -> None:
    await session.execute(
        text(
            """
            insert into deployment_spend (day, cost_microusd) values (current_date, :cost)
            on conflict (day) do update
                set cost_microusd = deployment_spend.cost_microusd + excluded.cost_microusd
            """
        ),
        {"cost": cost_microusd},
    )
