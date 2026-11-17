"""In-memory stand-ins for ports. The contract tests hold them to the real behaviour."""

import asyncio
from collections import deque
from dataclasses import dataclass
from uuid import UUID

from frontdesk.queue.port import Delivery, TriggerQueue
from frontdesk.queue.triggers import Trigger


@dataclass
class _Entry:
    trigger: Trigger
    failed_attempts: int = 0


class InMemoryTriggerQueue:
    def __init__(self, *, max_deliveries: int = 5) -> None:
        self._max_deliveries = max_deliveries
        self._waiting: dict[UUID, deque[_Entry]] = {}
        self._held: set[UUID] = set()
        self._seen: set[str] = set()
        self._changed = asyncio.Condition()
        self.set_aside: list[Trigger] = []

    async def send(self, trigger: Trigger, *, deduplication_id: str) -> None:
        async with self._changed:
            if deduplication_id in self._seen:
                return
            self._seen.add(deduplication_id)
            self._waiting.setdefault(trigger.conversation_id, deque()).append(_Entry(trigger))
            self._changed.notify_all()

    async def lease(self, *, wait_seconds: float) -> "InMemoryLease | None":
        async with self._changed:
            try:
                async with asyncio.timeout(wait_seconds):
                    while (conversation_id := self._next_free()) is None:
                        await self._changed.wait()
            except TimeoutError:
                return None
            self._held.add(conversation_id)
            return InMemoryLease(self, conversation_id)

    async def close(self) -> None:
        return None

    async def emptied(self) -> None:
        """Returns once nothing is waiting and nothing is held."""
        async with self._changed:
            await self._changed.wait_for(lambda: not self._held and not any(self._waiting.values()))

    def _next_free(self) -> UUID | None:
        return next(
            (
                conversation_id
                for conversation_id, entries in self._waiting.items()
                if entries and conversation_id not in self._held
            ),
            None,
        )


class InMemoryLease:
    def __init__(self, queue: InMemoryTriggerQueue, conversation_id: UUID) -> None:
        self._queue = queue
        self._conversation_id = conversation_id

    async def receive(self) -> Delivery | None:
        entries = self._queue._waiting.get(self._conversation_id)
        if not entries:
            return None
        entry = entries[0]
        return Delivery(trigger=entry.trigger, attempt=entry.failed_attempts + 1, token=entry)

    async def ack(self, delivery: Delivery) -> None:
        async with self._queue._changed:
            self._entries().remove(_entry(delivery))
            self._queue._changed.notify_all()

    async def retry(self, delivery: Delivery) -> None:
        entry = _entry(delivery)
        entry.failed_attempts += 1
        if entry.failed_attempts >= self._queue._max_deliveries:
            self._entries().remove(entry)
            self._queue.set_aside.append(entry.trigger)

    async def release(self) -> None:
        async with self._queue._changed:
            self._queue._held.discard(self._conversation_id)
            self._queue._changed.notify_all()

    def _entries(self) -> deque[_Entry]:
        return self._queue._waiting[self._conversation_id]


def _entry(delivery: Delivery) -> _Entry:
    assert isinstance(delivery.token, _Entry)
    return delivery.token


async def waiting_triggers(queue: TriggerQueue) -> list[Trigger]:
    """Takes everything the queue has to deliver right now."""
    triggers: list[Trigger] = []
    while (lease := await queue.lease(wait_seconds=0)) is not None:
        while (delivery := await lease.receive()) is not None:
            triggers.append(delivery.trigger)
            await lease.ack(delivery)
        await lease.release()
    return triggers
