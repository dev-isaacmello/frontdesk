"""ING-8: the WhatsApp channel, against the shapes Meta documents."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text

from frontdesk.channels.port import (
    ChannelCost,
    ChannelRejectedError,
    ChannelUnavailableError,
    OutboundMessage,
)
from frontdesk.channels.whatsapp import SERVICE_MESSAGE, WhatsAppSender, parse, signed_by_meta
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.seed import BARBERSHOP
from tests.support import say
from tests.tools.conftest import NOW

SECRET = "the-app-secret"
NUMBER = "106540352242922"
USER = "BR.13491208655302741918"
PHONE = "5551999990000"


def notification(*messages: dict[str, Any], contacts: list[dict[str, Any]] | None = None) -> Any:
    value: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {"display_phone_number": "15550783881", "phone_number_id": NUMBER},
        "messages": list(messages),
    }
    if contacts is not None:
        value["contacts"] = contacts
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": value}]}]}


def text_message(**changed: Any) -> dict[str, Any]:
    message = {
        "from": PHONE,
        "from_user_id": USER,
        "id": "wamid.one",
        "timestamp": "1794996000",
        "type": "text",
        "text": {"body": "quanto custa o corte?"},
    }
    return {key: value for key, value in {**message, **changed}.items() if value is not None}


def test_ing_8_a_notification_is_genuine_only_when_signed_with_the_app_secret() -> None:
    body = b'{"entry": []}'
    signature = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()

    assert signed_by_meta(SECRET, body, signature)
    assert not signed_by_meta(SECRET, body + b" ", signature)
    assert not signed_by_meta("another-secret", body, signature)
    assert not signed_by_meta(SECRET, body, signature.removeprefix("sha256="))
    assert not signed_by_meta(SECRET, body, None)


def test_ing_8_a_text_message_is_read_with_its_number_its_customer_and_its_time() -> None:
    contacts = [{"profile": {"name": "Ana Souza"}, "wa_id": PHONE, "user_id": USER}]

    [received] = parse(notification(text_message(), contacts=contacts)).messages

    assert received.phone_number_id == NUMBER
    assert received.message.provider_message_id == "wamid.one"
    assert received.message.text == "quanto custa o corte?"
    assert received.message.sent_at == datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
    sender = received.message.sender
    assert (sender.channel, sender.external_id, sender.phone) == ("whatsapp", USER, PHONE)
    assert sender.display_name == "Ana Souza"


def test_ing_8_a_customer_with_a_username_and_no_phone_is_known_by_the_scoped_id() -> None:
    contacts = [{"profile": {"name": "Ana", "username": "anasouza"}, "user_id": USER}]

    [received] = parse(notification(text_message(**{"from": None}), contacts=contacts)).messages

    sender = received.message.sender
    assert (sender.external_id, sender.phone, sender.display_name) == (USER, None, "Ana")


def test_ing_8_an_older_payload_without_the_scoped_id_falls_back_to_the_phone() -> None:
    [received] = parse(notification(text_message(from_user_id=None))).messages

    assert received.message.sender.external_id == PHONE


@pytest.mark.parametrize(
    "message",
    [
        text_message(type="image", text=None),
        text_message(text={"body": ""}),
        text_message(id=None),
        text_message(timestamp="yesterday"),
        text_message(**{"from": None, "from_user_id": None}),
    ],
)
def test_ing_8_what_is_not_an_answerable_text_is_counted_and_not_read(
    message: dict[str, Any],
) -> None:
    read = parse(notification(message))

    assert (read.messages, read.ignored) == ([], 1)


@pytest.mark.parametrize(
    "payload",
    [None, [], "text", {"entry": "x"}, {"entry": [{"changes": [{"value": {"messages": [1]}}]}]}],
)
def test_ing_8_a_payload_of_any_shape_is_read_without_an_error(payload: Any) -> None:
    read = parse(payload)

    assert (read.messages, read.deliveries) == ([], [])


def test_cst_4_a_delivery_update_says_what_the_message_is_charged() -> None:
    def status(pricing: dict[str, Any] | None) -> dict[str, Any]:
        update: dict[str, Any] = {"id": "wamid.out", "status": "delivered", "timestamp": "1"}
        if pricing is not None:
            update["pricing"] = pricing
        return update

    value = {
        "metadata": {"phone_number_id": NUMBER},
        "statuses": [
            status({"billable": True, "pricing_model": "PMP", "category": "service"}),
            status({"billable": False, "pricing_model": "PMP", "category": "service"}),
            status({"billable": True, "pricing_model": "PMP", "category": "marketing"}),
            status(None),
        ],
    }

    deliveries = parse({"entry": [{"changes": [{"value": value}]}]}).deliveries

    # The rate of a service message is known; another category is left unknown, not guessed.
    assert [delivery.cost for delivery in deliveries] == [
        SERVICE_MESSAGE,
        ChannelCost(0, "BRL"),
        None,
        None,
    ]


class Graph:
    """Meta's Graph API, as a transport that records what it was asked."""

    def __init__(self, *answers: httpx.Response | Exception) -> None:
        self.requests: list[httpx.Request] = []
        self._answers = list(answers)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self._answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


ACCEPTED = {
    "messaging_product": "whatsapp",
    "contacts": [{"input": PHONE, "wa_id": PHONE}],
    "messages": [{"id": "wamid.sent", "message_status": "accepted"}],
}


def refusal(status: int, code: int) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": "x", "code": code}})


class Slept:
    def __init__(self) -> None:
        self.seconds: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.seconds.append(seconds)


def sender_with(
    sessions: SessionFactory, graph: Graph, slept: Slept, now: datetime = NOW
) -> WhatsAppSender:
    return WhatsAppSender(
        httpx.AsyncClient(transport=httpx.MockTransport(graph)),
        sessions,
        SecretStr("the-access-token"),
        clock=lambda: now,
        sleep=slept,
    )


async def outbound(sessions: SessionFactory, *, phone: str | None = PHONE) -> OutboundMessage:
    receipt = await say(sessions, "oi", "m1")
    return OutboundMessage(
        message_id=receipt.conversation_id,
        tenant_id=BARBERSHOP.id,
        conversation_id=receipt.conversation_id,
        channel="whatsapp",
        recipient_external_id=USER,
        text="O corte custa R$ 45,00.",
        account_external_id=NUMBER,
        recipient_phone=phone,
    )


async def test_ing_8_a_reply_is_posted_to_the_number_of_the_tenant_with_the_token(
    sessions: SessionFactory,
) -> None:
    graph = Graph(httpx.Response(200, json=ACCEPTED))

    receipt = await sender_with(sessions, graph, Slept()).send(await outbound(sessions))

    [request] = graph.requests
    assert request.url == f"https://graph.facebook.com/v27.0/{NUMBER}/messages"
    assert request.headers["Authorization"] == "Bearer the-access-token"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": PHONE,
        "type": "text",
        "text": {"preview_url": False, "body": "O corte custa R$ 45,00."},
    }
    # Meta charges on delivery and says so later, so the cost is unknown at this point.
    assert (receipt.provider_message_id, receipt.cost) == ("wamid.sent", None)


async def test_ing_8_a_customer_without_a_phone_is_addressed_by_the_scoped_id(
    sessions: SessionFactory,
) -> None:
    graph = Graph(httpx.Response(200, json=ACCEPTED))

    await sender_with(sessions, graph, Slept()).send(await outbound(sessions, phone=None))

    sent = json.loads(graph.requests[0].content)
    assert (sent.get("to"), sent["recipient"]) == (None, USER)


@pytest.mark.parametrize(
    "answer",
    [
        refusal(500, 1),
        refusal(400, 131056),
        refusal(429, 130429),
        httpx.ConnectTimeout("slow"),
        httpx.ConnectError("down"),
    ],
)
async def test_ing_8_a_channel_that_is_down_or_throttling_can_be_tried_again(
    sessions: SessionFactory, answer: httpx.Response | Exception
) -> None:
    sender = sender_with(sessions, Graph(answer), Slept())

    with pytest.raises(ChannelUnavailableError):
        await sender.send(await outbound(sessions))


@pytest.mark.parametrize("answer", [refusal(400, 131047), refusal(401, 190), refusal(400, 131026)])
async def test_ing_8_a_closed_window_or_a_dead_token_is_a_refusal_and_not_a_retry(
    sessions: SessionFactory, answer: httpx.Response
) -> None:
    sender = sender_with(sessions, Graph(answer), Slept())

    with pytest.raises(ChannelRejectedError) as refused:
        await sender.send(await outbound(sessions))

    assert refused.value.reason == f"{answer.status_code}/{answer.json()['error']['code']}"


async def test_ing_8_a_second_message_to_the_same_customer_waits_out_the_six_seconds(
    sessions: SessionFactory,
) -> None:
    message = await outbound(sessions)
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        await session.execute(
            text(
                "insert into messages (tenant_id, conversation_id, direction, author, body, "
                "occurred_at, sent_at) values (:t, :c, 'out', 'agent', 'oi', :at, :at)"
            ),
            {"t": BARBERSHOP.id, "c": message.conversation_id, "at": NOW - timedelta(seconds=2)},
        )
    slept = Slept()

    await sender_with(sessions, Graph(httpx.Response(200, json=ACCEPTED)), slept).send(message)

    assert slept.seconds == [4.0]


async def test_ing_8_the_first_message_to_a_customer_is_not_delayed(
    sessions: SessionFactory,
) -> None:
    slept = Slept()
    graph = Graph(httpx.Response(200, json=ACCEPTED))

    await sender_with(sessions, graph, slept).send(await outbound(sessions))

    assert slept.seconds == []


@pytest.mark.parametrize(
    ("as_whatsapp_names_it", "as_it_is_dialled"),
    [
        # A mobile outside São Paulo, Rio and Espírito Santo: WhatsApp's id has eight digits
        # after the area code, and the number as dialled has nine.
        ("555188887777", "5551988887777"),
        # Already nine digits, a landline, and a number of another country: as they came.
        ("5511988887777", "5511988887777"),
        ("555133334444", "555133334444"),
        ("14155550123", "14155550123"),
    ],
)
async def test_ing_8_a_brazilian_mobile_is_addressed_with_its_ninth_digit(
    sessions: SessionFactory, as_whatsapp_names_it: str, as_it_is_dialled: str
) -> None:
    """The first real reply was refused: the recipient was "not in allowed list".

    The customer's number arrives as WhatsApp's id for it, without the ninth digit, and the
    Graph API matched the number literally against the list of a test number. Addressed as
    dialled, the same message was accepted, and its answer named the shorter id.
    """
    graph = Graph(httpx.Response(200, json=ACCEPTED))

    await sender_with(sessions, graph, Slept()).send(
        await outbound(sessions, phone=as_whatsapp_names_it)
    )

    assert json.loads(graph.requests[0].content)["to"] == as_it_is_dialled
