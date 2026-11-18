"""ING-8: the WhatsApp webhook, called in process, with a real database and queue."""

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from frontdesk.api.app import ApiDeps, create_app
from frontdesk.channels.webchat import PostgresNotifications
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.queue.port import TriggerQueue
from frontdesk.seed import ARENA, BARBERSHOP, link_whatsapp_number
from tests.channels.test_whatsapp import NUMBER, PHONE, USER, notification, text_message
from tests.conftest import Database
from tests.fakes import waiting_triggers
from tests.support import RecordingSender, scripted_worker
from tests.tools.conftest import NOW

APP_SECRET = "the-secret-of-the-meta-app"
VERIFY_TOKEN = "a-token-typed-into-the-dashboard"
WEBHOOK = "/channels/whatsapp/webhook"


def app_with(
    sessions: SessionFactory, queue: TriggerQueue, database: Database, **whatsapp: str
) -> httpx.AsyncClient:
    app = create_app(
        ApiDeps(
            sessions=sessions,
            queue=queue,
            notifications=PostgresNotifications(database.app_dsn),
            webchat_secret="a-shared-secret-between-the-panel-and-the-api",
            clock=lambda: NOW,
            agent=scripted_worker(sessions, RecordingSender())[0].agent,
            **whatsapp,
        )
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


@pytest.fixture
async def client(
    sessions: SessionFactory, queue: TriggerQueue, database: Database
) -> AsyncIterator[httpx.AsyncClient]:
    await link_whatsapp_number(sessions, BARBERSHOP.slug, NUMBER)
    async with app_with(
        sessions,
        queue,
        database,
        whatsapp_app_secret=APP_SECRET,
        whatsapp_verify_token=VERIFY_TOKEN,
    ) as http:
        yield http


async def post(
    client: httpx.AsyncClient, payload: Any, *, secret: str = APP_SECRET
) -> httpx.Response:
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return await client.post(WEBHOOK, content=body, headers={"X-Hub-Signature-256": signature})


async def stored(sessions: SessionFactory, tenant: Any = BARBERSHOP) -> list[tuple[Any, ...]]:
    async with tenant_transaction(sessions, tenant.id) as session:
        rows = await session.execute(
            text(
                "select m.body, i.channel, i.external_id, i.phone from messages m "
                "join conversations c on c.id = m.conversation_id "
                "join customer_identities i on i.customer_id = c.customer_id order by m.id"
            )
        )
    return [tuple(row) for row in rows]


async def test_ing_8_meta_confirms_the_subscription_with_the_token_we_chose(
    client: httpx.AsyncClient,
) -> None:
    ours = {"hub.mode": "subscribe", "hub.challenge": "1158201444"}

    confirmed = await client.get(WEBHOOK, params={**ours, "hub.verify_token": VERIFY_TOKEN})
    refused = await client.get(WEBHOOK, params={**ours, "hub.verify_token": "a-guess"})

    assert (confirmed.status_code, confirmed.text) == (200, "1158201444")
    assert refused.status_code == 403


async def test_ing_8_a_signed_message_is_stored_for_the_tenant_of_the_number_and_enqueued(
    client: httpx.AsyncClient, sessions: SessionFactory, queue: TriggerQueue
) -> None:
    response = await post(client, notification(text_message()))

    assert (response.status_code, response.json()) == (200, {"stored": 1})
    assert await stored(sessions) == [("quanto custa o corte?", "whatsapp", USER, PHONE)]
    assert await stored(sessions, ARENA) == []
    [trigger] = await waiting_triggers(queue)
    assert trigger.tenant_id == BARBERSHOP.id


async def test_ing_8_a_notification_that_meta_did_not_sign_stores_nothing(
    client: httpx.AsyncClient, sessions: SessionFactory, queue: TriggerQueue
) -> None:
    forged = await post(client, notification(text_message()), secret="not-the-app-secret")
    unsigned = await client.post(WEBHOOK, content=json.dumps(notification(text_message())))

    assert (forged.status_code, unsigned.status_code) == (401, 401)
    assert await stored(sessions) == []
    assert await waiting_triggers(queue) == []


async def test_ing_2_a_notification_delivered_twice_is_stored_and_enqueued_once(
    client: httpx.AsyncClient, sessions: SessionFactory, queue: TriggerQueue
) -> None:
    first = await post(client, notification(text_message()))
    again = await post(client, notification(text_message()))

    assert (first.json(), again.json()) == ({"stored": 1}, {"stored": 0})
    assert len(await stored(sessions)) == 1
    assert len(await waiting_triggers(queue)) == 1


async def test_ing_8_a_message_to_a_number_no_tenant_owns_is_acknowledged_and_dropped(
    client: httpx.AsyncClient, sessions: SessionFactory
) -> None:
    payload = notification(text_message())
    payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"] = "999"

    response = await post(client, payload)

    # An error here would make Meta deliver the same notification again for days.
    assert (response.status_code, response.json()) == (200, {"stored": 0})
    assert await stored(sessions) == []


async def test_cst_4_a_delivery_update_records_what_the_message_was_charged(
    client: httpx.AsyncClient, sessions: SessionFactory
) -> None:
    await post(client, notification(text_message()))
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        await session.execute(
            text(
                "insert into messages (tenant_id, conversation_id, direction, author, body, "
                "occurred_at, sent_at, provider_message_id) select tenant_id, id, 'out', "
                "'agent', 'O corte custa R$ 45,00.', now(), now(), 'wamid.out' from conversations"
            )
        )
    delivered = {
        "id": "wamid.out",
        "status": "delivered",
        "timestamp": "1794996010",
        "recipient_id": PHONE,
        "pricing": {"billable": True, "pricing_model": "PMP", "category": "service"},
    }
    update = {"metadata": {"phone_number_id": NUMBER}, "statuses": [delivered]}

    response = await post(client, {"entry": [{"changes": [{"value": update}]}]})

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        charged = await session.execute(
            text(
                "select channel_cost_micros, channel_cost_currency from messages "
                "where provider_message_id = 'wamid.out'"
            )
        )
    assert response.status_code == 200
    assert charged.all() == [(35_000, "BRL")]


async def test_ing_8_without_its_secrets_the_webhook_does_not_exist(
    sessions: SessionFactory, queue: TriggerQueue, database: Database
) -> None:
    async with app_with(sessions, queue, database) as http:
        response = await http.post(WEBHOOK, content=b"{}")

    assert response.status_code == 404
