"""Creates the roles, the database and the extensions of a cluster.

Runs once per cluster with a superuser connection, before any migration. Migrations
then run as the owner role, and the services connect as the application role, which
owns nothing and cannot bypass row-level security.
"""

from dataclasses import dataclass

import psycopg
from psycopg import sql

OWNER_ROLE = "frontdesk_owner"
APP_ROLE = "frontdesk_app"
EXTENSIONS = ("btree_gist",)


@dataclass(frozen=True)
class BootstrapPlan:
    database: str
    owner_password: str
    app_password: str


def bootstrap(superuser_dsn: str, plan: BootstrapPlan) -> None:
    with psycopg.connect(superuser_dsn, autocommit=True) as cluster:
        _ensure_role(cluster, OWNER_ROLE, plan.owner_password)
        _ensure_role(cluster, APP_ROLE, plan.app_password)
        _ensure_database(cluster, plan.database)

    with psycopg.connect(superuser_dsn, dbname=plan.database, autocommit=True) as database:
        for extension in EXTENSIONS:
            database.execute(
                sql.SQL("create extension if not exists {}").format(sql.Identifier(extension))
            )


def _ensure_role(conn: psycopg.Connection, role: str, password: str) -> None:
    exists = conn.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
    statement = "alter role {} login password {}" if exists else "create role {} login password {}"
    conn.execute(sql.SQL(statement).format(sql.Identifier(role), sql.Literal(password)))


def _ensure_database(conn: psycopg.Connection, database: str) -> None:
    exists = conn.execute("select 1 from pg_database where datname = %s", (database,)).fetchone()
    if exists:
        return
    conn.execute(
        sql.SQL("create database {} owner {}").format(
            sql.Identifier(database), sql.Identifier(OWNER_ROLE)
        )
    )
