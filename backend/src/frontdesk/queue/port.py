"""The trigger queue as the rest of the system sees it.

A trigger says that a conversation has work waiting. The queue hands out one conversation
at a time: whoever holds the lease is the only one receiving that conversation's triggers
until the lease is released, while other conversations go to other holders.
"""

from dataclasses import dataclass, field
from typing import Protocol

from frontdesk.queue.triggers import Trigger


@dataclass(frozen=True)
class Delivery:
    trigger: Trigger
    attempt: int
    """1 on the first delivery. It grows only when a delivery is given back with `retry`."""

    token: object = field(compare=False, repr=False)
    """What the queue needs to settle this delivery. Opaque to the caller."""


class Lease(Protocol):
    """An exclusive hold on the triggers of one conversation."""

    async def receive(self) -> Delivery | None:
        """The oldest trigger waiting for this conversation, or None when there is none.

        One at a time: a trigger only says that the conversation has work, and handling
        one usually leaves nothing for the next to do.
        """
        ...

    async def ack(self, delivery: Delivery) -> None:
        """Removes a trigger that was handled."""
        ...

    async def retry(self, delivery: Delivery) -> None:
        """Gives a trigger back to be delivered again, counting one failed attempt.

        A trigger that fails too many times is set aside by the queue and is no longer
        delivered.
        """
        ...

    async def release(self) -> None:
        """Ends the hold. Triggers neither acknowledged nor retried are delivered again."""
        ...


class TriggerQueue(Protocol):
    async def send(self, trigger: Trigger, *, deduplication_id: str) -> None:
        """Enqueues a trigger. A second send with the same id, soon after, is dropped."""
        ...

    async def lease(self, *, wait_seconds: float) -> Lease | None:
        """Takes the next conversation with triggers waiting that nobody else holds.

        Returns None when there was none within about `wait_seconds`.
        """
        ...

    async def close(self) -> None: ...
