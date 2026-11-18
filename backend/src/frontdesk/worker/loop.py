"""Taking conversations from the queue and handling their triggers."""

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress

from frontdesk import logs
from frontdesk.domain.conversations import ConversationBusyError
from frontdesk.providers.port import ModelRejectedError
from frontdesk.queue.port import Lease, TriggerQueue
from frontdesk.queue.triggers import Trigger
from frontdesk.worker.handler import WorkerDeps, give_up, handle

log = logging.getLogger(__name__)

_LEASE_WAIT_SECONDS = 20
MAX_ATTEMPTS = 5
"""Deliveries of one trigger before the worker gives up. The queue's own maximum delivery
count is the same number, so the delivery that gives up is also the one that sends the
trigger to the dead-letter queue."""
_QUEUE_RETRY_SECONDS = 5


def backoff_seconds(attempt: int) -> float:
    """How long a failed trigger is held before it is given back: 2, 4, 8, 16, then 30 s."""
    return float(min(2**attempt, 30))


async def run(
    deps: WorkerDeps, queue: TriggerQueue, stop: asyncio.Event, *, concurrency: int
) -> None:
    """Handles up to `concurrency` conversations side by side until asked to stop.

    A turn in progress is finished first. A wait for work is dropped.
    """
    await asyncio.gather(
        # Each waits a little longer than the one before, so that they do not all time
        # out and reconnect in the same instant, leaving nobody listening.
        *(_pump(deps, queue, stop, _LEASE_WAIT_SECONDS + index) for index in range(concurrency))
    )


async def _pump(
    deps: WorkerDeps, queue: TriggerQueue, stop: asyncio.Event, wait_seconds: float
) -> None:
    stopped = asyncio.create_task(stop.wait())
    try:
        while not stop.is_set():
            waiting = asyncio.create_task(queue.lease(wait_seconds=wait_seconds))
            await asyncio.wait({waiting, stopped}, return_when=asyncio.FIRST_COMPLETED)
            if not waiting.done():
                waiting.cancel()
                with suppress(asyncio.CancelledError):
                    await waiting
                return
            try:
                lease = waiting.result()
            except Exception as error:
                log.error("queue_unavailable", extra=logs.failure(error))
                await asyncio.sleep(_QUEUE_RETRY_SECONDS)
                continue
            if lease is not None:
                try:
                    await handle_conversation(deps, lease)
                except Exception as error:
                    # The queue failed while settling or releasing, for instance because
                    # the session lock was lost. Nothing is repeated to the customer: the
                    # trigger comes back and finds the turn already closed.
                    log.error("lease_failed", extra=logs.failure(error))
    finally:
        stopped.cancel()


async def process_next(
    deps: WorkerDeps,
    queue: TriggerQueue,
    *,
    wait_seconds: float = _LEASE_WAIT_SECONDS,
    pause: Callable[[int], float] = backoff_seconds,
) -> int:
    """Takes the next conversation with triggers waiting and handles them.

    Returns how many triggers were acknowledged.
    """
    lease = await queue.lease(wait_seconds=wait_seconds)
    if lease is None:
        return 0
    return await handle_conversation(deps, lease, pause=pause)


async def handle_conversation(
    deps: WorkerDeps, lease: Lease, *, pause: Callable[[int], float] = backoff_seconds
) -> int:
    """Handles the next trigger of a leased conversation, then lets the conversation go.

    Returns 1 when the trigger was acknowledged. Triggers behind it stay in the queue,
    which offers the conversation again.
    """
    try:
        delivery = await lease.receive()
        if delivery is None:
            return 0
        trigger = delivery.trigger
        try:
            await handle(deps, trigger)
        except ConversationBusyError:
            # Another worker still holds the conversation. The trigger goes back as it
            # came, without counting an attempt, and is offered again after the pause.
            await asyncio.sleep(pause(1))
            return 0
        except Exception as error:
            log.error(
                "turn_failed",
                extra={
                    "tenant_id": str(trigger.tenant_id),
                    "conversation_id": str(trigger.conversation_id),
                    "attempt": delivery.attempt,
                    **logs.failure(error),
                },
            )
            # A request the provider rejects as it is will be rejected again: no retry.
            if delivery.attempt >= MAX_ATTEMPTS or isinstance(error, ModelRejectedError):
                await _give_up(deps, trigger)
            else:
                # The conversation stays leased during the pause, so nothing of it runs
                # out of order and a dependency that is down is not hit in a tight loop.
                await asyncio.sleep(pause(delivery.attempt))
            await lease.retry(delivery)
            return 0
        await lease.ack(delivery)
        return 1
    finally:
        await lease.release()


async def _give_up(deps: WorkerDeps, trigger: Trigger) -> None:
    try:
        await give_up(deps, trigger)
    except Exception as error:
        # Whatever broke the turn can break this too. The trigger still goes to the
        # dead-letter queue, where the alarm on its size is the last line.
        log.error(
            "give_up_failed",
            extra={
                "tenant_id": str(trigger.tenant_id),
                "conversation_id": str(trigger.conversation_id),
                **logs.failure(error),
            },
        )
