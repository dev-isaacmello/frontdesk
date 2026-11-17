"""Alembic environment. Migrations are hand-written SQL and run as the owner role."""

import os

from alembic import context
from sqlalchemy import create_engine, pool


def _database_url() -> str:
    return (
        context.config.get_main_option("sqlalchemy.url")
        or os.environ["FRONTDESK_MIGRATIONS_DATABASE_URL"]
    )


def run_migrations() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
