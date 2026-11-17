"""Shared fixtures: one real PostgreSQL per test session, migrated and seeded."""

from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine
from testcontainers.community.postgres import PostgresContainer

from frontdesk.db.bootstrap import APP_ROLE, OWNER_ROLE, BootstrapPlan, bootstrap
from frontdesk.db.session import SessionFactory, create_engine, create_session_factory
from frontdesk.seed import seed
from tests.fakes import InMemoryTriggerQueue

POSTGRES_IMAGE = "pgvector/pgvector:pg18"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PLAN = BootstrapPlan(database="frontdesk", owner_password="owner", app_password="app")
WRITTEN_BY_TESTS = (
    "model_calls",
    "messages",
    "turns",
    "inbound_events",
    "conversations",
    "bookings",
    "schedule_blocks",
    "customer_identities",
    "customers",
)


@dataclass(frozen=True)
class Database:
    host: str
    port: int

    def url(self, role: str, password: str, database: str = PLAN.database) -> str:
        return f"postgresql+psycopg://{role}:{password}@{self.host}:{self.port}/{database}"

    @property
    def superuser_dsn(self) -> str:
        return f"postgresql://postgres:postgres@{self.host}:{self.port}/postgres"

    @property
    def app_dsn(self) -> str:
        return (
            f"postgresql://{APP_ROLE}:{PLAN.app_password}@{self.host}:{self.port}/{PLAN.database}"
        )

    @property
    def app_url(self) -> str:
        return self.url(APP_ROLE, PLAN.app_password)

    @property
    def owner_url(self) -> str:
        return self.url(OWNER_ROLE, PLAN.owner_password)


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    with PostgresContainer(POSTGRES_IMAGE, username="postgres", password="postgres") as container:
        database = Database(
            container.get_container_host_ip(), int(container.get_exposed_port(5432))
        )
        bootstrap(database.superuser_dsn, PLAN)
        migrate(database.owner_url, "head")
        yield database


def migrate(owner_url: str, revision: str) -> None:
    config = Config(BACKEND_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", owner_url)
    if revision == "head":
        command.upgrade(config, revision)
    else:
        command.downgrade(config, revision)


@pytest.fixture(scope="session")
async def engine(database: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(database.app_url)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def sessions(engine: AsyncEngine) -> SessionFactory:
    factory = create_session_factory(engine)
    await seed(factory)
    return factory


@pytest.fixture(autouse=True)
def clean_slate(database: Database) -> None:
    """Removes what earlier tests wrote, keeping the seeded catalog."""
    with psycopg.connect(database.superuser_dsn, dbname=PLAN.database) as connection:
        tables = connection.execute(
            """
            select string_agg(quote_ident(tablename), ', ') from pg_tables
            where schemaname = 'public' and tablename = any(%s)
            """,
            (list(WRITTEN_BY_TESTS),),
        ).fetchone()
        if tables and tables[0]:
            connection.execute(f"truncate {tables[0]} cascade")


@pytest.fixture
def queue() -> InMemoryTriggerQueue:
    """The stand-in the API and worker tests run on. See tests/queue for its contract."""
    return InMemoryTriggerQueue()
