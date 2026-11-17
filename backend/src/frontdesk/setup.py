"""Prepares a database: roles, schema and the seed. `python -m frontdesk.setup`.

Reads its own variables, separate from the services, because it is the only program
that connects with more than the application role:

    FRONTDESK_SUPERUSER_DSN            libpq string of a superuser, for roles and extensions
    FRONTDESK_DATABASE_NAME            database to create
    FRONTDESK_OWNER_PASSWORD           password given to the owner role
    FRONTDESK_APP_PASSWORD             password given to the application role
    FRONTDESK_MIGRATIONS_DATABASE_URL  SQLAlchemy URL of the owner role
    FRONTDESK_DATABASE_URL             SQLAlchemy URL of the application role
"""

import asyncio
import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config

from frontdesk import logs
from frontdesk.db.bootstrap import BootstrapPlan, bootstrap
from frontdesk.db.session import create_engine, create_session_factory
from frontdesk.seed import seed

log = logging.getLogger("frontdesk.setup")


def main() -> None:
    logs.configure()
    env = os.environ
    bootstrap(
        env["FRONTDESK_SUPERUSER_DSN"],
        BootstrapPlan(
            database=env["FRONTDESK_DATABASE_NAME"],
            owner_password=env["FRONTDESK_OWNER_PASSWORD"],
            app_password=env["FRONTDESK_APP_PASSWORD"],
        ),
    )
    log.info("roles_and_database_ready")

    # env.py reads the owner URL from the environment.
    command.upgrade(Config(Path(env.get("FRONTDESK_ALEMBIC_INI", "alembic.ini"))), "head")
    log.info("schema_migrated")

    asyncio.run(_seed(env["FRONTDESK_DATABASE_URL"]))
    log.info("seed_applied")


async def _seed(database_url: str) -> None:
    engine = create_engine(database_url)
    try:
        await seed(create_session_factory(engine))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    main()
