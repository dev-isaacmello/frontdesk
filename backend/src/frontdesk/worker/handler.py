"""What a worker does with one trigger."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from opentelemetry.trace import SpanKind

from frontdesk import telemetry
from frontdesk.agent import prompts
from frontdesk.agent.graph import AgentDeps, resume_turn, run_turn
from frontdesk.agent.turn import TurnInput, TurnResult
from frontdesk.channels.port import ChannelSender
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain import approvals, conversations
from frontdesk.domain.customers import Channel
from frontdesk.queue.triggers import Trigger

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerDeps:
    sessions: SessionFactory
    agent: AgentDeps
    senders: Mapping[Channel, ChannelSender]
    clock: Callable[[], datetime]
    quiet_window: timedelta = timedelta(0)
    """How long the customer has to be silent before the turn starts, so that a burst of
    short messages is answered once."""

    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep


_MAX_QUIET_WAITS = 5
"""A customer who never stops typing does not postpone the answer for ever."""


async def handle(deps: WorkerDeps, trigger: Trigger) -> None:
    """Does what the conversation is waiting for, then sends what is in its outbox.

    First a turn that was paused for the owner and now has a decision, then the turn over
    the customer messages that are waiting. Safe to call again for the same trigger: a
    finished turn is not run twice, and a reply that was written but not sent is sent
    without calling the model.
    """
    with telemetry.span(
        "handle conversation",
        {
            "frontdesk.tenant_id": str(trigger.tenant_id),
            "frontdesk.conversation_id": str(trigger.conversation_id),
        },
        parent=trigger.traceparent,
        kind=SpanKind.CONSUMER,
    ):
        await _resume_decided(deps, trigger)
        await _let_a_burst_finish(deps, trigger)
        async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
            turn = await conversations.open_turn(session, trigger.conversation_id, deps.clock())

        if turn is not None:
            await _run(deps, trigger, turn, run_turn(deps.agent, turn))

        await _deliver(deps, trigger)


async def _resume_decided(deps: WorkerDeps, trigger: Trigger) -> None:
    async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
        decided = await approvals.next_decided(session, trigger.conversation_id)
        if decided is None:
            return
        turn = await conversations.reopen_turn(
            session, trigger.conversation_id, decided.turn_id, deps.clock()
        )
    if turn is None:
        return
    await _run(
        deps,
        trigger,
        turn,
        resume_turn(deps.agent, turn, approved=decided.approved),
        resumed_approval=decided.approval_id,
    )


async def _run(
    deps: WorkerDeps,
    trigger: Trigger,
    turn: TurnInput,
    running: Awaitable[TurnResult],
    *,
    resumed_approval: UUID | None = None,
) -> None:
    """Awaits a turn and writes its result under the lease the turn was opened with."""
    try:
        result = await running
        log.info(
            "turn_finished",
            extra={
                "tenant_id": str(trigger.tenant_id),
                "conversation_id": str(trigger.conversation_id),
                "outcome": result.outcome,
                "handoff_reason": result.handoff_reason,
                "blocked_drafts": result.blocks,
            },
        )
        async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
            await conversations.close_turn(
                session, trigger.conversation_id, turn, result, deps.clock()
            )
            if resumed_approval is not None:
                await approvals.mark_resumed(session, resumed_approval, deps.clock())
    except Exception:
        # The retry must not wait for the lease of the attempt that just failed.
        async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
            await conversations.release_lease(session, trigger.conversation_id, turn.lease_epoch)
        raise


async def _let_a_burst_finish(deps: WorkerDeps, trigger: Trigger) -> None:
    for _ in range(_MAX_QUIET_WAITS):
        async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
            newest = await conversations.newest_waiting(session, trigger.conversation_id)
        if newest is None:
            return
        remaining = deps.quiet_window - (deps.clock() - newest)
        if remaining <= timedelta(0):
            return
        await deps.sleep(remaining.total_seconds())


async def give_up(deps: WorkerDeps, trigger: Trigger) -> None:
    """Stops retrying a conversation whose turn keeps failing and hands it to a person."""
    async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
        await conversations.give_up(
            session, trigger.conversation_id, prompts.HANDOFF_NOTICE, deps.clock()
        )
    await _deliver(deps, trigger)


async def _deliver(deps: WorkerDeps, trigger: Trigger) -> None:
    async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
        outbox = await conversations.undelivered(session, trigger.conversation_id)

    for message in outbox:
        with telemetry.span(f"send {message.channel}", kind=SpanKind.CLIENT):
            receipt = await deps.senders[message.channel].send(message)
        async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
            await conversations.mark_sent(session, message.message_id, receipt, deps.clock())
