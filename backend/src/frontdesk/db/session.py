"""Database sessions that are scoped to one tenant for their whole life.

Tenant isolation is enforced by row-level security, and the policies read a setting
that exists only inside a transaction. Setting it in one place, at the start of every
transaction, is what keeps a pooled connection from carrying a tenant to the next
request (ADR 0004).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import Connection, event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

_TENANT_KEY = "tenant_id"
_SET_TENANT = text("select set_config('app.tenant_id', :tenant_id, true)")

type SessionFactory = async_sessionmaker[AsyncSession]


class TenantSession(Session):
    """A session whose transactions all begin by naming their tenant."""


@event.listens_for(TenantSession, "after_begin")
def _scope_transaction_to_tenant(
    session: Session, _transaction: SessionTransaction, connection: Connection
) -> None:
    tenant_id = session.info.get(_TENANT_KEY)
    if tenant_id is not None:
        connection.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})


def create_engine(url: str, *, pool_size: int = 5, max_overflow: int = 10) -> AsyncEngine:
    return create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=pool_size,
        max_overflow=max_overflow,
        # Statement parameters include message bodies and names. They stay out of
        # exception messages, and therefore out of logs.
        hide_parameters=True,
    )


def create_session_factory(engine: AsyncEngine) -> SessionFactory:
    return async_sessionmaker(engine, sync_session_class=TenantSession, expire_on_commit=False)


@asynccontextmanager
async def tenant_transaction(
    factory: SessionFactory, tenant_id: UUID
) -> AsyncGenerator[AsyncSession]:
    """One transaction that can only see and write the rows of `tenant_id`."""
    async with factory(info={_TENANT_KEY: tenant_id}) as session, session.begin():
        yield session
