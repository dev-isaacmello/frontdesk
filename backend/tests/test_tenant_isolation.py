"""Tenant isolation, exercised as the runtime database role against real PostgreSQL."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from frontdesk.db.session import (
    SessionFactory,
    create_engine,
    create_session_factory,
    tenant_transaction,
)
from frontdesk.seed import ARENA, BARBERSHOP
from tests.conftest import Database

COUNT_SERVICES = text("select count(*) from services")

pytestmark = pytest.mark.usefixtures("sessions")


async def test_ten_1_runtime_role_reads_nothing_without_a_tenant(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        visible = await connection.scalar(COUNT_SERVICES)

    assert visible == 0


async def test_ten_1_runtime_role_writes_nothing_without_a_tenant(engine: AsyncEngine) -> None:
    insert = text(
        "insert into services (tenant_id, name, duration_minutes) values (:tenant, 'Intruso', 10)"
    )

    with pytest.raises(ProgrammingError, match="row-level security"):
        async with engine.begin() as connection:
            await connection.execute(insert, {"tenant": BARBERSHOP.id})


async def test_ten_2_a_tenant_reads_only_its_own_rows(sessions: SessionFactory) -> None:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        own = await session.scalar(COUNT_SERVICES)
        other = await session.scalar(
            text("select count(*) from services where tenant_id = :other"), {"other": ARENA.id}
        )

    assert own == 3
    assert other == 0


async def test_ten_2_a_tenant_cannot_write_rows_of_another(sessions: SessionFactory) -> None:
    insert = text(
        "insert into services (tenant_id, name, duration_minutes) values (:other, 'Intruso', 10)"
    )

    with pytest.raises(ProgrammingError, match="row-level security"):
        async with tenant_transaction(sessions, BARBERSHOP.id) as session:
            await session.execute(insert, {"other": ARENA.id})


async def test_ten_2_a_tenant_cannot_change_rows_of_another(sessions: SessionFactory) -> None:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        changed = await session.execute(
            text("update services set name = 'Tomado' where tenant_id = :other returning id"),
            {"other": ARENA.id},
        )
        deleted = await session.execute(
            text("delete from service_prices where tenant_id = :other returning service_id"),
            {"other": ARENA.id},
        )

    assert changed.all() == []
    assert deleted.all() == []


async def test_ten_3_tenant_does_not_survive_on_a_pooled_connection(database: Database) -> None:
    single_connection = create_engine(database.app_url, pool_size=1, max_overflow=0)
    factory = create_session_factory(single_connection)
    try:
        async with tenant_transaction(factory, BARBERSHOP.id) as session:
            first_backend = await session.scalar(text("select pg_backend_pid()"))
            assert await session.scalar(COUNT_SERVICES) == 3

        async with single_connection.connect() as connection:
            second_backend = await connection.scalar(text("select pg_backend_pid()"))
            visible = await connection.scalar(COUNT_SERVICES)
    finally:
        await single_connection.dispose()

    assert second_backend == first_backend
    assert visible == 0
