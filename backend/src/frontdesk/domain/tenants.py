"""The tenant of the current transaction."""

from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import Tenant


async def load_tenant(session: AsyncSession, tenant_id: UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise LookupError(f"tenant {tenant_id} is not visible in this transaction")
    return tenant


def timezone_of(tenant: Tenant) -> ZoneInfo:
    return ZoneInfo(tenant.timezone)
