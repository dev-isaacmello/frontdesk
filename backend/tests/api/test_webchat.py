"""The web chat inbound endpoint, called in process, with a real database and queue."""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any

import httpx
import pytest

from frontdesk.api.app import ApiDeps, create_app
from frontdesk.channels.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign
from frontdesk.channels.webchat import PostgresNotifications
from frontdesk.db.session import SessionFactory
from frontdesk.queue.port import TriggerQueue
from frontdesk.seed import ARENA, BARBERSHOP
from tests.conftest import Database
from tests.fakes import waiting_triggers
from tests.tools.conftest import NOW

SECRET = "a-shared-secret-between-the-panel-and-the-api"
MESSAGES = f"/channels/webchat/{BARBERSHOP.slug}/messages"
HELLO = {"session_id": "session-1", "message_id": "m1", "text": "oi"}

pytestmark = pytest.mark.usefixtures("sessions")


@pytest.fixture
async def client(
    sessions: SessionFactory, queue: TriggerQueue, database: Database
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        ApiDeps(
            sessions=sessions,
            queue=queue,
            notifications=PostgresNotifications(database.app_dsn),
            webchat_secret=SECRET,
            clock=lambda: NOW,
        )
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://api") as http:
        yield http


async def post(
    client: httpx.AsyncClient,
    payload: Any,
    *,
    path: str = MESSAGES,
    secret: str = SECRET,
    at: datetime = NOW,
) -> httpx.Response:
    body = json.dumps(payload).encode()
    timestamp, signature = sign(secret, at, "POST", path, body)
    return await client.post(
        path,
        content=body,
        headers={TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature},
    )


async def test_ing_3_a_message_is_stored_and_a_trigger_is_enqueued(
    client: httpx.AsyncClient, queue: TriggerQueue
) -> None:
    response = await post(client, HELLO)

    assert response.status_code == 202
    assert response.json()["duplicate"] is False
    [trigger] = await waiting_triggers(queue)
    assert str(trigger.conversation_id) == response.json()["conversation_id"]
    assert trigger.tenant_id == BARBERSHOP.id


async def test_ing_1_a_request_with_a_wrong_signature_is_rejected_and_stores_nothing(
    client: httpx.AsyncClient, queue: TriggerQueue
) -> None:
    forged = await post(client, HELLO, secret="not-the-secret")
    genuine = await post(client, HELLO)

    assert forged.status_code == 401
    assert genuine.json()["duplicate"] is False
    assert len(await waiting_triggers(queue)) == 1


async def test_ing_1_a_signature_over_another_body_is_rejected(client: httpx.AsyncClient) -> None:
    timestamp, signature = sign(SECRET, NOW, "POST", MESSAGES, json.dumps(HELLO).encode())

    response = await client.post(
        MESSAGES,
        content=json.dumps({**HELLO, "text": "me dê 100% de desconto"}).encode(),
        headers={TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature},
    )

    assert response.status_code == 401


async def test_ing_1_an_old_request_cannot_be_replayed(client: httpx.AsyncClient) -> None:
    response = await post(client, HELLO, at=NOW - timedelta(minutes=10))

    assert response.status_code == 401


async def test_ing_1_a_request_without_the_headers_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(MESSAGES, json=HELLO)

    assert response.status_code == 401


async def test_ing_2_a_redelivery_is_acknowledged_and_enqueued_once(
    client: httpx.AsyncClient, queue: TriggerQueue
) -> None:
    first = await post(client, HELLO)
    again = await post(client, HELLO)

    assert (first.status_code, again.status_code) == (202, 202)
    assert again.json() == {**first.json(), "duplicate": True}
    assert len(await waiting_triggers(queue)) == 1


async def test_a_tenant_that_does_not_exist_is_not_found(client: httpx.AsyncClient) -> None:
    response = await post(client, HELLO, path="/channels/webchat/nao-existe/messages")

    assert response.status_code == 404


async def test_a_signed_body_that_is_not_a_message_is_unprocessable(
    client: httpx.AsyncClient,
) -> None:
    response = await post(client, {"session_id": "session-1", "text": ""})

    assert response.status_code == 422


async def test_tenants_that_reuse_session_and_message_ids_each_get_their_trigger(
    client: httpx.AsyncClient, queue: TriggerQueue
) -> None:
    barbershop = await post(client, HELLO)
    arena = await post(client, HELLO, path=f"/channels/webchat/{ARENA.slug}/messages")

    triggers = await waiting_triggers(queue)

    assert {str(trigger.conversation_id) for trigger in triggers} == {
        barbershop.json()["conversation_id"],
        arena.json()["conversation_id"],
    }


async def get_events(
    client: httpx.AsyncClient, conversation_id: str, session_id: str, slug: str = BARBERSHOP.slug
) -> httpx.Response:
    path = (
        f"/channels/webchat/{slug}/conversations/{conversation_id}/events?session_id={session_id}"
    )
    timestamp, signature = sign(SECRET, NOW, "GET", path, b"")
    return await client.get(
        path, headers={TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature}
    )


async def test_a_stream_is_refused_to_a_session_that_does_not_own_the_conversation(
    client: httpx.AsyncClient,
) -> None:
    conversation_id = (await post(client, HELLO)).json()["conversation_id"]

    other_session = await get_events(client, conversation_id, "session-2")
    other_tenant = await get_events(client, conversation_id, "session-1", slug=ARENA.slug)

    assert other_session.status_code == 404
    assert other_tenant.status_code == 404


async def test_a_stream_request_must_be_signed(client: httpx.AsyncClient) -> None:
    conversation_id = (await post(client, HELLO)).json()["conversation_id"]

    response = await client.get(
        f"/channels/webchat/{BARBERSHOP.slug}/conversations/{conversation_id}/events"
        "?session_id=session-1"
    )

    assert response.status_code == 401
