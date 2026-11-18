"""APR-1 to APR-3: an action that waits for the owner, and what happens with the decision."""

import json
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text

from frontdesk.agent.prompts import WAIT_NOTICE
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain import approvals
from frontdesk.domain.approvals import ApprovalInfo
from frontdesk.domain.bookings import Booked
from frontdesk.domain.conversations import Receipt
from frontdesk.providers.scripted import calls, says
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import BARBERSHOP
from frontdesk.tools.bookings import CancelBookingInput, CreateBookingInput, cancel_booking
from frontdesk.tools.bookings import create_booking as create_booking_tool
from frontdesk.worker.handler import handle
from tests.support import IN_SCOPE, RecordingSender, say, scripted_worker
from tests.tools.conftest import NOW, another_call, customer_of, local

type NewSaver = Callable[[], AsyncPostgresSaver]

CORTE = BARBERSHOP.service_id("Corte")
CAIO = BARBERSHOP.resource_id("Caio")
# NOW is 07:00 on the 18th and the barbershop asks for three hours of notice.
IN_TWO_HOURS = local(18, 9)
TOMORROW = local(19, 10)
ASKED = "preciso cancelar meu horário"


def trigger_of(receipt: Receipt) -> Trigger:
    return Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id)


async def book(sessions: SessionFactory, starts_at: datetime) -> UUID:
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    wanted = CreateBookingInput(service_id=CORTE, resource_id=CAIO, starts_at=starts_at)
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        booked = await create_booking_tool.run(ana, wanted, session)
    assert isinstance(booked, Booked)
    return booked.booking.booking_id


async def status_of(sessions: SessionFactory, booking_id: UUID) -> str:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        status = await session.scalar(
            text("select status from bookings where id = :id"), {"id": booking_id}
        )
    return str(status)


async def waiting(sessions: SessionFactory) -> list[ApprovalInfo]:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        return await approvals.pending_of_tenant(session)


async def decide(sessions: SessionFactory, approval: ApprovalInfo, *, approved: bool) -> None:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        woken = await approvals.decide(session, approval.id, approved=approved, now=NOW)
    assert woken == approval.conversation_id


async def ask_to_cancel(
    sessions: SessionFactory, sender: RecordingSender, booking: UUID, saver: NewSaver
) -> Receipt:
    """The customer asks, the planner calls the tool, and the turn stops at the gate."""
    cancel = calls("cancel_booking", {"booking_id": str(booking)})
    deps, _ = scripted_worker(sessions, sender, IN_SCOPE, cancel, checkpointer=saver())
    receipt = await say(sessions, ASKED, "m1")
    await handle(deps, trigger_of(receipt))
    return receipt


async def test_apr_1_a_late_cancellation_waits_for_the_owner_and_the_customer_is_told(
    sessions: SessionFactory, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, IN_TWO_HOURS)
    sender = RecordingSender()

    await ask_to_cancel(sessions, sender, booking, checkpointer)

    [pending] = await waiting(sessions)
    assert [message.text for message in sender.sent] == [WAIT_NOTICE]
    assert await status_of(sessions, booking) == "confirmed"
    assert (pending.rule, pending.tool) == ("late_change", "cancel_booking")
    assert pending.arguments == {"booking_id": str(booking)}


async def test_apr_2_an_approved_action_runs_in_whichever_worker_gets_the_decision(
    sessions: SessionFactory, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, IN_TWO_HOURS)
    sender = RecordingSender()
    receipt = await ask_to_cancel(sessions, sender, booking, checkpointer)
    [pending] = await waiting(sessions)

    await decide(sessions, pending, approved=True)
    other_worker, _ = scripted_worker(
        sessions,
        sender,
        says("Pronto, cancelei o seu horário das 9h."),
        checkpointer=checkpointer(),
    )
    await handle(other_worker, trigger_of(receipt))

    assert [message.text for message in sender.sent] == [
        WAIT_NOTICE,
        "Pronto, cancelei o seu horário das 9h.",
    ]
    assert await status_of(sessions, booking) == "cancelled"
    assert await waiting(sessions) == []


async def test_apr_2_a_rejected_action_does_not_run_and_the_customer_is_told(
    sessions: SessionFactory, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, IN_TWO_HOURS)
    sender = RecordingSender()
    receipt = await ask_to_cancel(sessions, sender, booking, checkpointer)
    [pending] = await waiting(sessions)

    await decide(sessions, pending, approved=False)
    kept = "O responsável não autorizou o cancelamento. Seu horário continua marcado."
    other_worker, provider = scripted_worker(
        sessions, sender, says(kept), checkpointer=checkpointer()
    )
    await handle(other_worker, trigger_of(receipt))

    told = json.loads(provider.requests[0].messages[-1].content)
    assert told == {"error": "rejected_by_owner"}
    assert [message.text for message in sender.sent] == [WAIT_NOTICE, kept]
    assert await status_of(sessions, booking) == "confirmed"


async def test_apr_2_an_approved_action_is_validated_again_when_it_runs(
    sessions: SessionFactory, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, IN_TWO_HOURS)
    sender = RecordingSender()
    receipt = await ask_to_cancel(sessions, sender, booking, checkpointer)
    [pending] = await waiting(sessions)
    ana = await customer_of(sessions, BARBERSHOP, "Ana")
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        await cancel_booking.run(another_call(ana), CancelBookingInput(booking_id=booking), session)

    await decide(sessions, pending, approved=True)
    gone = "Não consegui cancelar: esse horário já não está ativo."
    other_worker, provider = scripted_worker(
        sessions, sender, says(gone), checkpointer=checkpointer()
    )
    await handle(other_worker, trigger_of(receipt))

    refused = json.loads(provider.requests[0].messages[-1].content)
    assert refused["status"] == "refused"
    assert sender.sent[-1].text == gone


async def test_apr_2_a_decision_is_acted_on_once(
    sessions: SessionFactory, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, IN_TWO_HOURS)
    sender = RecordingSender()
    receipt = await ask_to_cancel(sessions, sender, booking, checkpointer)
    [pending] = await waiting(sessions)
    await decide(sessions, pending, approved=True)
    worker, provider = scripted_worker(
        sessions, sender, says("Pronto, cancelei o seu horário."), checkpointer=checkpointer()
    )

    await handle(worker, trigger_of(receipt))
    await handle(worker, trigger_of(receipt))

    assert len(provider.requests) == 1
    assert len(sender.sent) == 2


async def test_apr_3_while_an_approval_is_pending_new_messages_are_answered(
    sessions: SessionFactory, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, IN_TWO_HOURS)
    sender = RecordingSender()
    await ask_to_cancel(sessions, sender, booking, checkpointer)

    quote = calls("quote", {"service_ids": [str(CORTE)], "starts_at": "2026-11-19T14:00:00"})
    worker, _ = scripted_worker(
        sessions,
        sender,
        IN_SCOPE,
        quote,
        says("O corte sai por R$ 45,00."),
        checkpointer=checkpointer(),
    )
    await handle(worker, trigger_of(await say(sessions, "e quanto custa o corte?", "m2")))

    assert [message.text for message in sender.sent] == [WAIT_NOTICE, "O corte sai por R$ 45,00."]
    assert len(await waiting(sessions)) == 1
    assert await status_of(sessions, booking) == "confirmed"


async def test_apr_1_a_second_sensitive_request_does_not_open_a_second_approval(
    sessions: SessionFactory, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, IN_TWO_HOURS)
    sender = RecordingSender()
    await ask_to_cancel(sessions, sender, booking, checkpointer)

    again = calls("cancel_booking", {"booking_id": str(booking)})
    said = "Seu pedido já está com o responsável. Assim que ele responder eu aviso."
    worker, provider = scripted_worker(
        sessions, sender, IN_SCOPE, again, says(said), checkpointer=checkpointer()
    )
    await handle(worker, trigger_of(await say(sessions, "e aí, cancelou?", "m2")))

    told = json.loads(provider.requests[-1].messages[-1].content)
    assert told == {"error": "approval_already_pending"}
    assert len(await waiting(sessions)) == 1


async def test_apr_1_a_change_with_enough_notice_needs_no_approval(
    sessions: SessionFactory, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, TOMORROW)
    sender = RecordingSender()
    cancel = calls("cancel_booking", {"booking_id": str(booking)})
    worker, _ = scripted_worker(
        sessions, sender, IN_SCOPE, cancel, says("Pronto, cancelei."), checkpointer=checkpointer()
    )

    await handle(worker, trigger_of(await say(sessions, ASKED, "m1")))

    assert [message.text for message in sender.sent] == ["Pronto, cancelei."]
    assert await status_of(sessions, booking) == "cancelled"
    assert await waiting(sessions) == []
