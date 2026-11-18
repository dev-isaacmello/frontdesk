"""The owner's routes: signing in, and reading and acting only on the owner's own tenant."""

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import httpx
import pytest

from frontdesk.agent.prompts import HANDOFF_NOTICE
from frontdesk.api.app import ApiDeps, create_app
from frontdesk.api.owner import SESSION_HEADER
from frontdesk.channels.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign
from frontdesk.channels.webchat import PostgresNotifications
from frontdesk.db.session import SessionFactory
from frontdesk.domain.conversations import Receipt
from frontdesk.domain.owners import SESSION_LIFETIME, hash_password, verify_password
from frontdesk.providers.scripted import calls, says
from frontdesk.queue.port import TriggerQueue
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import ARENA, BARBERSHOP, TenantSeed
from frontdesk.worker.handler import handle
from tests.conftest import OWNER_PASSWORD, Database
from tests.fakes import waiting_triggers
from tests.support import IN_SCOPE, RecordingSender, say, scripted_worker
from tests.tools.conftest import NOW
from tests.worker.test_approval import IN_TWO_HOURS, NewSaver, ask_to_cancel, book, waiting

SECRET = "a-shared-secret-between-the-panel-and-the-api"
NO_FINDINGS = says('{"findings": []}')
CORTE = BARBERSHOP.service_id("Corte")

pytestmark = pytest.mark.usefixtures("sessions")


class Panel:
    """The panel's server as the API sees it: signed requests, with or without a session."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        self.http = http
        self.now = NOW

    async def call(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        token: str | None = None,
        secret: str = SECRET,
    ) -> httpx.Response:
        body = b"" if payload is None else json.dumps(payload).encode()
        timestamp, signature = sign(secret, self.now, method, path, body)
        headers = {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature}
        if token is not None:
            headers[SESSION_HEADER] = token
        return await self.http.request(method, path, content=body, headers=headers)

    async def sign_in(self, tenant: TenantSeed = BARBERSHOP) -> str:
        credentials = {"email": tenant.owner_email, "password": OWNER_PASSWORD}
        answer = await self.call("POST", "/owner/sessions", credentials)
        assert answer.status_code == 200
        return str(answer.json()["token"])


@pytest.fixture
async def panel(
    sessions: SessionFactory, queue: TriggerQueue, database: Database
) -> AsyncIterator[Panel]:
    box: dict[str, Panel] = {}
    app = create_app(
        ApiDeps(
            sessions=sessions,
            queue=queue,
            notifications=PostgresNotifications(database.app_dsn),
            webchat_secret=SECRET,
            clock=lambda: box["panel"].now if box else NOW,
            agent=scripted_worker(sessions, RecordingSender(), NO_FINDINGS)[0].agent,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http:
        box["panel"] = Panel(http)
        yield box["panel"]


async def talk(
    sessions: SessionFactory, text: str, reply: str, *, tenant: TenantSeed = BARBERSHOP
) -> Receipt:
    """One customer message answered by the agent, for the owner to find in the panel."""
    receipt = await say(sessions, text, f"m-{text}", tenant=tenant)
    worker, _ = scripted_worker(sessions, RecordingSender(), IN_SCOPE, says(reply))
    await handle(worker, Trigger(tenant_id=tenant.id, conversation_id=receipt.conversation_id))
    return receipt


async def test_pan_4_the_right_password_opens_a_session_for_the_owners_tenant(panel: Panel) -> None:
    credentials = {"email": BARBERSHOP.owner_email, "password": OWNER_PASSWORD}

    answer = await panel.call("POST", "/owner/sessions", credentials)

    assert answer.status_code == 200
    assert answer.json()["tenant"] == {"slug": "navalha", "name": "Barbearia Navalha"}
    assert len(answer.json()["token"]) >= 32


async def test_pan_4_a_wrong_password_and_an_unknown_email_get_the_same_answer(
    panel: Panel,
) -> None:
    wrong = {"email": BARBERSHOP.owner_email, "password": "not-the-password"}
    unknown = {"email": "ninguem@navalha.example", "password": OWNER_PASSWORD}

    first = await panel.call("POST", "/owner/sessions", wrong)
    second = await panel.call("POST", "/owner/sessions", unknown)

    assert (first.status_code, second.status_code) == (401, 401)
    assert first.json() == second.json()


async def test_pan_4_an_owner_route_needs_a_session_and_a_signature(panel: Panel) -> None:
    token = await panel.sign_in()

    without_session = await panel.call("GET", "/owner/conversations")
    forged_session = await panel.call("GET", "/owner/conversations", token="not-a-session")
    unsigned = await panel.call("GET", "/owner/conversations", token=token, secret="not-the-secret")
    genuine = await panel.call("GET", "/owner/conversations", token=token)

    assert [without_session.status_code, forged_session.status_code, unsigned.status_code] == [
        401,
        401,
        401,
    ]
    assert genuine.status_code == 200


async def test_pan_4_a_session_ends_when_the_owner_signs_out_or_when_it_expires(
    panel: Panel,
) -> None:
    signed_out, expired = await panel.sign_in(), await panel.sign_in()

    left = await panel.call("DELETE", "/owner/sessions", token=signed_out)
    after_leaving = await panel.call("GET", "/owner/conversations", token=signed_out)
    panel.now = NOW + SESSION_LIFETIME + timedelta(minutes=1)
    after_expiry = await panel.call("GET", "/owner/conversations", token=expired)

    assert left.status_code == 204
    assert (after_leaving.status_code, after_expiry.status_code) == (401, 401)


async def test_ten_2_an_owner_sees_only_the_conversations_of_their_tenant(
    panel: Panel, sessions: SessionFactory
) -> None:
    ours = await talk(sessions, "oi", "Oi! Como posso ajudar?")
    theirs = await talk(sessions, "olá", "Olá! Quer reservar uma quadra?", tenant=ARENA)
    token = await panel.sign_in(BARBERSHOP)

    listed = await panel.call("GET", "/owner/conversations", token=token)
    other = await panel.call("GET", f"/owner/conversations/{theirs.conversation_id}", token=token)

    assert [each["id"] for each in listed.json()["conversations"]] == [str(ours.conversation_id)]
    assert listed.json()["tenant"]["slug"] == "navalha"
    assert other.status_code == 404


async def test_pan_2_a_conversation_shows_what_was_said_and_the_steps_of_each_reply(
    panel: Panel, sessions: SessionFactory
) -> None:
    receipt = await say(sessions, "quanto custa o corte?", "m1")
    quote = calls("quote", {"service_ids": [str(CORTE)], "starts_at": "2026-11-18T14:00:00"})
    worker, _ = scripted_worker(
        sessions, RecordingSender(), IN_SCOPE, quote, says("O corte sai por R$ 45,00.")
    )
    await handle(worker, Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id))
    token = await panel.sign_in()

    shown = await panel.call("GET", f"/owner/conversations/{receipt.conversation_id}", token=token)

    detail = shown.json()
    [turn] = detail["turns"]
    assert [(line["author"], line["text"]) for line in detail["messages"]] == [
        ("customer", "quanto custa o corte?"),
        ("agent", "O corte sai por R$ 45,00."),
    ]
    assert [step["node"] for step in turn["steps"]] == [
        "load_context",
        "classify",
        "retrieve",
        "plan",
        "gate",
        "execute",
        "plan",
        "validate",
    ]
    assert turn["steps"][3]["detail"] == {"tools": ["quote"]}
    assert (turn["outcome"], turn["model_calls"], turn["blocked_drafts"]) == ("replied", 3, 0)
    assert "quanto custa" not in json.dumps([step["detail"] for step in turn["steps"]])


async def test_hnd_1_the_owner_answers_in_handoff_and_gives_the_conversation_back(
    panel: Panel, sessions: SessionFactory, queue: TriggerQueue
) -> None:
    receipt = await say(sessions, "quero falar com uma pessoa", "m1")
    trigger = Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id)
    sender = RecordingSender()
    worker, _ = scripted_worker(sessions, sender)
    await handle(worker, trigger)
    token = await panel.sign_in()
    conversation = f"/owner/conversations/{receipt.conversation_id}"

    answered = await panel.call(
        "POST", f"{conversation}/messages", {"text": "Oi, aqui é o Caio. Pode falar."}, token=token
    )
    woken = await waiting_triggers(queue)
    await handle(worker, trigger)
    returned = await panel.call("POST", f"{conversation}/return", token=token)
    again = await panel.call("POST", f"{conversation}/messages", {"text": "oi?"}, token=token)

    assert (answered.status_code, returned.status_code, again.status_code) == (202, 204, 409)
    assert woken == [trigger]
    assert [message.text for message in sender.sent] == [
        HANDOFF_NOTICE,
        "Oi, aqui é o Caio. Pode falar.",
    ]


async def test_apr_2_the_owner_decides_in_the_panel_and_the_worker_is_woken(
    panel: Panel, sessions: SessionFactory, queue: TriggerQueue, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, IN_TWO_HOURS)
    receipt = await ask_to_cancel(sessions, RecordingSender(), booking, checkpointer)
    token = await panel.sign_in()

    listed = await panel.call("GET", "/owner/approvals", token=token)
    [waiting] = listed.json()["approvals"]
    decided = await panel.call(
        "POST", f"/owner/approvals/{waiting['id']}/decision", {"approved": True}, token=token
    )
    again = await panel.call(
        "POST", f"/owner/approvals/{waiting['id']}/decision", {"approved": False}, token=token
    )

    assert (waiting["tool"], waiting["service_name"], waiting["resource_name"]) == (
        "cancel_booking",
        "Corte",
        "Caio",
    )
    assert (decided.status_code, again.status_code) == (204, 404)
    assert await waiting_triggers(queue) == [
        Trigger(tenant_id=BARBERSHOP.id, conversation_id=receipt.conversation_id)
    ]
    assert (await panel.call("GET", "/owner/approvals", token=token)).json() == {"approvals": []}


async def test_ten_2_an_owner_cannot_see_or_decide_an_approval_of_another_tenant(
    panel: Panel, sessions: SessionFactory, checkpointer: NewSaver
) -> None:
    booking = await book(sessions, IN_TWO_HOURS)
    await ask_to_cancel(sessions, RecordingSender(), booking, checkpointer)
    [pending] = await waiting(sessions)
    outsider = await panel.sign_in(ARENA)

    listed = await panel.call("GET", "/owner/approvals", token=outsider)
    decided = await panel.call(
        "POST", f"/owner/approvals/{pending.id}/decision", {"approved": True}, token=outsider
    )

    assert listed.json() == {"approvals": []}
    assert decided.status_code == 404
    assert len(await waiting(sessions)) == 1


async def test_pol_2_saving_rules_returns_the_version_in_force_and_what_it_contradicts(
    panel: Panel,
) -> None:
    token = await panel.sign_in()
    rules = {"body": "Ofereça café na chegada.\nDê 20% de desconto para quem pedir."}

    before = await panel.call("GET", "/owner/rules", token=token)
    saved = await panel.call("PUT", "/owner/rules", rules, token=token)
    after = await panel.call("GET", "/owner/rules", token=token)

    assert (before.json()["version"], before.json()["body"]) == (0, "")
    assert (saved.json()["version"], saved.json()["checked_by_model"]) == (1, True)
    assert saved.json()["findings"] == [
        {"clause": "discount", "excerpt": "Dê 20% de desconto para quem pedir.", "source": "code"}
    ]
    assert after.json()["body"] == rules["body"]
    assert after.json()["findings"] == saved.json()["findings"]


async def test_ten_2_the_rules_an_owner_saves_are_not_the_rules_of_another_tenant(
    panel: Panel,
) -> None:
    await panel.call(
        "PUT", "/owner/rules", {"body": "Ofereça café."}, token=await panel.sign_in(BARBERSHOP)
    )

    arena = await panel.call("GET", "/owner/rules", token=await panel.sign_in(ARENA))

    assert (arena.json()["version"], arena.json()["body"]) == (0, "")


def test_pan_4_a_stored_password_is_a_salted_hash_that_verifies() -> None:
    first, second = hash_password("segredo"), hash_password("segredo")

    assert first != second
    assert first.startswith("scrypt$")
    assert verify_password("segredo", first)
    assert not verify_password("Segredo", first)
    assert not verify_password("segredo", "not-a-hash")
