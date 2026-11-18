"""Prepares a database: roles, schema and the seed. `python -m frontdesk.setup`.

Reads its own variables, separate from the services, because it is the only program
that connects with more than the application role:

    FRONTDESK_SUPERUSER_DSN            libpq string of a superuser, for roles and extensions
    FRONTDESK_DATABASE_NAME            database to create
    FRONTDESK_OWNER_PASSWORD           password given to the owner role
    FRONTDESK_APP_PASSWORD             password given to the application role
    FRONTDESK_MIGRATIONS_DATABASE_URL  SQLAlchemy URL of the owner role
    FRONTDESK_DATABASE_URL             SQLAlchemy URL of the application role
    FRONTDESK_DEMO_OWNER_PASSWORD      password of the demo owner accounts; none if unset
"""

import asyncio
import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import make_url

from frontdesk import logs
from frontdesk.agent import checkpoints
from frontdesk.db.bootstrap import APP_ROLE, BootstrapPlan, bootstrap
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

    owner_dsn = make_url(env["FRONTDESK_MIGRATIONS_DATABASE_URL"]).set(drivername="postgresql")
    asyncio.run(
        checkpoints.create_tables(owner_dsn.render_as_string(hide_password=False), APP_ROLE)
    )
    log.info("checkpoint_tables_ready")

    owner_password = env.get("FRONTDESK_DEMO_OWNER_PASSWORD") or None
    asyncio.run(_seed(env["FRONTDESK_DATABASE_URL"], owner_password))
    log.info("seed_applied", extra={"owner_accounts": owner_password is not None})


async def _seed(database_url: str, owner_password: str | None) -> None:
    engine = create_engine(database_url)
    try:
        await seed(create_session_factory(engine), owner_password)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    main()
