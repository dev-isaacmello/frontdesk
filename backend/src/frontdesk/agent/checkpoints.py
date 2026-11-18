"""Where a paused turn is kept: LangGraph's checkpointer on the same PostgreSQL.

A turn only needs a checkpoint when it stops for the owner's approval, which can last
hours and end in another process. The tables are the library's own and are created by its
`setup`, as the owner role; the application role gets the rights to use them.

What a checkpoint may contain is an explicit list of this project's types. Anything else
found in one is refused when it is read.
"""

import psycopg
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from frontdesk.agent.turn import HistoryMessage, TurnInput
from frontdesk.guardrail import Count, Day, Duration, Money, Sourced, TimeOfDay
from frontdesk.providers.port import Message, ToolCall

STATE_TYPES = (
    TurnInput,
    HistoryMessage,
    Message,
    ToolCall,
    Sourced,
    Money,
    TimeOfDay,
    Day,
    Duration,
    Count,
)
_TABLES = "checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations"

type Pool = AsyncConnectionPool[psycopg.AsyncConnection[DictRow]]


async def create_tables(owner_dsn: str, app_role: str) -> None:
    """Creates or migrates the checkpoint tables. Run by the database setup, as the owner."""
    async with await psycopg.AsyncConnection.connect(
        owner_dsn, autocommit=True, row_factory=dict_row
    ) as connection:
        await AsyncPostgresSaver(connection).setup()
        await connection.execute(f"grant select, insert, update, delete on {_TABLES} to {app_role}")


def pool(app_dsn: str) -> Pool:
    """A pool for the checkpointer, to be opened by whoever owns the process lifetime."""
    return AsyncConnectionPool(
        app_dsn,
        kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": 0},
        min_size=1,
        max_size=4,
        open=False,
    )


def saver(connections: Pool) -> AsyncPostgresSaver:
    return AsyncPostgresSaver(
        connections, serde=JsonPlusSerializer(allowed_msgpack_modules=STATE_TYPES)
    )
