"""The operator's switch over the whole deployment."""

import psycopg

from frontdesk.ops import set_model_calls
from tests.conftest import PLAN, Database


def flag(database: Database) -> bool:
    with psycopg.connect(database.superuser_dsn, dbname=PLAN.database) as connection:
        row = connection.execute(
            "select enabled from system_flags where name = 'model_calls'"
        ).fetchone()
    assert row is not None
    return bool(row[0])


def test_cst_5_the_operator_switches_model_calls_off_and_on_as_the_owner_role(
    database: Database,
) -> None:
    set_model_calls(database.owner_dsn, enabled=False)
    off = flag(database)
    set_model_calls(database.owner_dsn, enabled=True)

    assert (off, flag(database)) == (False, True)
