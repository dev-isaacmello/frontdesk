"""The tenant of the current transaction."""

from datetime import time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import BusinessHours, Tenant


async def load_tenant(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise LookupError(f"tenant {tenant_id} is not visible in this transaction")
    return tenant


def timezone_of(tenant: Tenant) -> ZoneInfo:
    return ZoneInfo(tenant.timezone)


async def opening_hours(session: AsyncSession, tenant_id: UUID) -> dict[int, tuple[time, time]]:
    """Opening and closing time by ISO weekday. A weekday that is missing is closed."""
    rows = await session.scalars(select(BusinessHours).where(BusinessHours.tenant_id == tenant_id))
    return {row.weekday: (row.opens, row.closes) for row in rows}
