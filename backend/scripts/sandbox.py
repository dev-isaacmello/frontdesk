"""A PostgreSQL that lives for one script run: roles, schema and the seeded tenants."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from frontdesk.db.bootstrap import APP_ROLE, OWNER_ROLE, BootstrapPlan, bootstrap
from frontdesk.db.session import SessionFactory, create_engine, create_session_factory
from frontdesk.providers.embeddings import Embedder
from frontdesk.seed import seed

BACKEND = Path(__file__).resolve().parents[1]
PLAN = BootstrapPlan(database="frontdesk", owner_password="owner", app_password="app")  # noqa: S106


@dataclass(frozen=True)
class Sandbox:
    sessions: SessionFactory
    superuser_dsn: str
    database: str


@asynccontextmanager
async def sandbox(embedder: Embedder | None = None) -> AsyncIterator[Sandbox]:
    with PostgresContainer(
        "pgvector/pgvector:pg18",
        username="postgres",
        password="postgres",  # noqa: S106  not a secret: the container dies with the run
    ) as db:
        host, port = db.get_container_host_ip(), int(db.get_exposed_port(5432))
        superuser_dsn = f"postgresql://postgres:postgres@{host}:{port}/postgres"
        bootstrap(superuser_dsn, PLAN)
        config = Config(BACKEND / "alembic.ini")
        config.set_main_option(
            "sqlalchemy.url",
            f"postgresql+psycopg://{OWNER_ROLE}:{PLAN.owner_password}@{host}:{port}/{PLAN.database}",
        )
        command.upgrade(config, "head")
        engine = create_engine(
            f"postgresql+psycopg://{APP_ROLE}:{PLAN.app_password}@{host}:{port}/{PLAN.database}"
        )
        sessions = create_session_factory(engine)
        await seed(sessions, embedder=embedder)
        try:
            yield Sandbox(sessions, superuser_dsn, PLAN.database)
        finally:
            await engine.dispose()
