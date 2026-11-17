"""HND-1: when the conversation goes to a person, and what the agent does afterwards."""

from uuid import UUID

from sqlalchemy import text

from frontdesk.agent.prompts import HANDOFF_NOTICE
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.conversations import Receipt
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import BARBERSHOP
from frontdesk.worker.handler import handle
from tests.support import WANTS_HUMAN, RecordingSender, conversation_row, say, scripted_worker


def trigger_of(receipt: Receipt) -> Trigger:
    return Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id)


async def handoff_reasons(sessions: SessionFactory, conversation_id: UUID) -> list[str]:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        rows = await session.execute(
            text("select reason from handoffs where conversation_id = :id order by opened_at"),
            {"id": conversation_id},
        )
    return [reason for (reason,) in rows]


async def test_hnd_1_a_customer_who_asks_for_a_person_gets_one_without_a_model_call(
    sessions: SessionFactory,
) -> None:
    sender = RecordingSender()
    deps, provider = scripted_worker(sessions, sender)
    receipt = await say(sessions, "Quero falar com um atendente, por favor", "m1")

    await handle(deps, trigger_of(receipt))

    assert [message.text for message in sender.sent] == [HANDOFF_NOTICE]
    assert provider.requests == []
    assert (await conversation_row(sessions, receipt.conversation_id))["mode"] == "handoff"
    assert await handoff_reasons(sessions, receipt.conversation_id) == ["customer_asked"]


async def test_hnd_1_the_model_can_also_notice_that_the_customer_wants_a_person(
    sessions: SessionFactory,
) -> None:
    sender = RecordingSender()
    deps, provider = scripted_worker(sessions, sender, WANTS_HUMAN)
    receipt = await say(sessions, "isso aqui não resolve nada, tem gente de verdade aí?", "m1")

    await handle(deps, trigger_of(receipt))

    assert [message.text for message in sender.sent] == [HANDOFF_NOTICE]
    assert len(provider.requests) == 1
    assert await handoff_reasons(sessions, receipt.conversation_id) == ["customer_asked"]


async def test_hnd_1_in_handoff_the_agent_stays_silent(sessions: SessionFactory) -> None:
    sender = RecordingSender()
    deps, provider = scripted_worker(sessions, sender)
    first = await say(sessions, "quero falar com uma pessoa", "m1")
    await handle(deps, trigger_of(first))

    later = await say(sessions, "quanto custa o corte?", "m2")
    await handle(deps, trigger_of(later))

    assert [message.text for message in sender.sent] == [HANDOFF_NOTICE]
    assert provider.requests == []
    assert later.conversation_id == first.conversation_id
    assert await handoff_reasons(sessions, first.conversation_id) == ["customer_asked"]


async def test_hnd_1_a_message_left_in_handoff_does_not_wake_the_agent_again(
    sessions: SessionFactory,
) -> None:
    deps, _ = scripted_worker(sessions, RecordingSender())
    first = await say(sessions, "quero falar com uma pessoa", "m1")
    await handle(deps, trigger_of(first))
    later = await say(sessions, "alguém aí?", "m2")
    await handle(deps, trigger_of(later))

    redelivered = await say(sessions, "alguém aí?", "m2")

    assert redelivered.pending is False
