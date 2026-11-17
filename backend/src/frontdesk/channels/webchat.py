"""The web chat channel: replies travel to open streams through PostgreSQL notifications.

The worker and the API are separate processes. A notification on commit is how the worker
tells every API process that a conversation has something new, without another service.
The notification carries only the conversation id; the stream reads the reply from the
outbox, so a notification that is lost costs a delay until the next heartbeat, not a message.
"""

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import psycopg
from sqlalchemy import text

from frontdesk.channels.port import OutboundMessage, SendReceipt
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain import conversations

_CHANNEL = "webchat"
_NOTIFY = text("select pg_notify(:channel, :conversation_id)")
_RECONNECT_SECONDS = 1.0

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ServerEvent:
    event: str
    data: dict[str, Any]
    id: str | None = None


class WebchatSender:
    """Sending on the web chat is announcing that the outbox has a reply to read."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions

    async def send(self, message: OutboundMessage) -> SendReceipt:
        async with tenant_transaction(self._sessions, message.tenant_id) as session:
            await session.execute(
                _NOTIFY, {"channel": _CHANNEL, "conversation_id": str(message.conversation_id)}
            )
        return SendReceipt(provider_message_id=None)


class PostgresNotifications:
    """One listening connection per process, fanned out to the streams that are open."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._subscribers: dict[str, set[asyncio.Event]] = defaultdict(set)
        self._listening = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._listen())
        await self._listening.wait()

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    @contextmanager
    def subscribe(self, conversation_id: UUID) -> Iterator[asyncio.Event]:
        key, wake = str(conversation_id), asyncio.Event()
        self._subscribers[key].add(wake)
        try:
            yield wake
        finally:
            self._subscribers[key].discard(wake)
            if not self._subscribers[key]:
                del self._subscribers[key]

    async def _listen(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._dsn, autocommit=True
                ) as connection:
                    await connection.execute(f"listen {_CHANNEL}")
                    self._listening.set()
                    # Whatever was announced while disconnected is found by a fresh read.
                    self._wake(*self._subscribers)
                    async for notification in connection.notifies():
                        self._wake(notification.payload)
            except psycopg.OperationalError:
                log.warning("notification listener lost its connection, reconnecting")
                await asyncio.sleep(_RECONNECT_SECONDS)

    def _wake(self, *keys: str) -> None:
        for key in keys:
            for wake in self._subscribers.get(key, ()):
                wake.set()


async def conversation_events(
    sessions: SessionFactory,
    notifications: PostgresNotifications,
    tenant_id: UUID,
    conversation_id: UUID,
    *,
    after: str | None,
    heartbeat_seconds: float = 15.0,
) -> AsyncIterator[ServerEvent]:
    """The agent's replies in a conversation, from a cursor on, as they appear."""
    cursor = UUID(after) if after else None
    with notifications.subscribe(conversation_id) as wake:
        while True:
            # Cleared before reading: a reply written during the read sets it again.
            wake.clear()
            async with tenant_transaction(sessions, tenant_id) as session:
                replies = await conversations.replies_after(session, conversation_id, cursor)
            for reply in replies:
                cursor = reply.message_id
                yield ServerEvent(
                    id=str(reply.message_id),
                    event="message",
                    data={"author": "agent", "text": reply.text},
                )
            try:
                async with asyncio.timeout(heartbeat_seconds):
                    await wake.wait()
            except TimeoutError:
                yield ServerEvent(event="heartbeat", data={})
