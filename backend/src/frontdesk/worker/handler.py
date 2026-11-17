"""What a worker does with one trigger."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from frontdesk.agent import prompts
from frontdesk.agent.graph import AgentDeps, run_turn
from frontdesk.channels.port import ChannelSender
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain import conversations
from frontdesk.domain.customers import Channel
from frontdesk.queue.triggers import Trigger


@dataclass(frozen=True)
class WorkerDeps:
    sessions: SessionFactory
    agent: AgentDeps
    senders: Mapping[Channel, ChannelSender]
    clock: Callable[[], datetime]


async def handle(deps: WorkerDeps, trigger: Trigger) -> None:
    """Runs the turn the conversation is waiting for, then sends what is in its outbox.

    Safe to call again for the same trigger: a finished turn is not run twice, and a
    reply that was written but not sent is sent without calling the model.
    """
    async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
        turn = await conversations.open_turn(session, trigger.conversation_id, deps.clock())

    if turn is not None:
        result = await run_turn(deps.agent, turn)
        async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
            await conversations.close_turn(
                session, trigger.conversation_id, turn, result, deps.clock()
            )

    await _deliver(deps, trigger)


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
        receipt = await deps.senders[message.channel].send(message)
        async with tenant_transaction(deps.sessions, trigger.tenant_id) as session:
            await conversations.mark_sent(
                session, message.message_id, receipt.provider_message_id, deps.clock()
            )
