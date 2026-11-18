"""What an operator does by hand to the whole deployment. `python -m frontdesk.ops`.

    python -m frontdesk.ops model-calls off    stop every model call; turns go to a person
    python -m frontdesk.ops model-calls on

Connects as the owner role, with FRONTDESK_MIGRATIONS_DATABASE_URL: the application role
can read the switch and cannot change it.
"""

import argparse
import os
import sys

import psycopg
from sqlalchemy import make_url


def set_model_calls(owner_dsn: str, *, enabled: bool) -> None:
    with psycopg.connect(owner_dsn) as connection:
        connection.execute(
            "update system_flags set enabled = %s, updated_at = now() where name = 'model_calls'",
            (enabled,),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Switches of the whole deployment.")
    parser.add_argument("flag", choices=["model-calls"])
    parser.add_argument("state", choices=["on", "off"])
    arguments = parser.parse_args()
    owner_url = make_url(os.environ["FRONTDESK_MIGRATIONS_DATABASE_URL"]).set(
        drivername="postgresql"
    )
    set_model_calls(
        owner_url.render_as_string(hide_password=False), enabled=arguments.state == "on"
    )
    print(f"model calls are {arguments.state}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
