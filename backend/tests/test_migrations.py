"""Every migration can be undone and applied again."""

import psycopg

from frontdesk.db.bootstrap import OWNER_ROLE, BootstrapPlan, bootstrap
from tests.conftest import PLAN, Database, migrate

SCRATCH = BootstrapPlan(
    database="frontdesk_migrations",
    owner_password=PLAN.owner_password,
    app_password=PLAN.app_password,
)


def test_migrations_downgrade_to_base_and_upgrade_again(database: Database) -> None:
    bootstrap(database.superuser_dsn, SCRATCH)
    owner_url = database.url(OWNER_ROLE, SCRATCH.owner_password, SCRATCH.database)

    migrate(owner_url, "head")
    migrate(owner_url, "base")
    leftovers = _objects_owned_by_owner(database)
    migrate(owner_url, "head")

    assert leftovers == ["alembic_version"]


def _objects_owned_by_owner(database: Database) -> list[str]:
    with psycopg.connect(database.superuser_dsn, dbname=SCRATCH.database) as connection:
        rows = connection.execute(
            """
            select relname::text from pg_class
            where relowner = %s::regrole and relkind in ('r', 'v', 'S')
            union all
            select proname::text from pg_proc where proowner = %s::regrole
            order by 1
            """,
            (OWNER_ROLE, OWNER_ROLE),
        ).fetchall()
    return [name for (name,) in rows]


LIKE_AZURE = BootstrapPlan(
    database="frontdesk_like_azure",
    owner_password=PLAN.owner_password,
    app_password=PLAN.app_password,
)


def test_inf_1_the_owner_role_can_migrate_a_database_whose_public_schema_it_does_not_own(
    database: Database,
) -> None:
    """What the first setup job met on Azure Database for PostgreSQL.

    There the `public` schema of a new database belongs to the administrators' role and
    not to the database's owner, so the owner role could not create its first table.
    """
    with psycopg.connect(database.superuser_dsn, dbname="template1", autocommit=True) as template:
        template.execute("alter schema public owner to postgres")
    try:
        bootstrap(database.superuser_dsn, LIKE_AZURE)

        migrate(database.url(OWNER_ROLE, LIKE_AZURE.owner_password, LIKE_AZURE.database), "head")
    finally:
        with psycopg.connect(
            database.superuser_dsn, dbname="template1", autocommit=True
        ) as template:
            template.execute("alter schema public owner to pg_database_owner")
