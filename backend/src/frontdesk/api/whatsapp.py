"""The WhatsApp webhook: verify, store once, enqueue, answer. No model is called here."""

import hmac
import json
import logging
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from opentelemetry.trace import SpanKind

from frontdesk import telemetry
from frontdesk.api.deps import ApiDeps
from frontdesk.channels.whatsapp import parse, signed_by_meta
from frontdesk.db.session import tenant_transaction
from frontdesk.domain.conversations import find_channel_account, receive, record_charge
from frontdesk.queue.triggers import Trigger

SIGNATURE_HEADER = "X-Hub-Signature-256"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WhatsAppWebhook:
    app_secret: str
    """Signs every notification Meta sends."""
    verify_token: str
    """Chosen by us and typed into Meta's dashboard, which sends it back once to prove
    that the endpoint is ours."""


def whatsapp_router(deps: ApiDeps, webhook: WhatsAppWebhook) -> APIRouter:
    router = APIRouter(prefix="/channels/whatsapp")

    @router.get("/webhook")
    async def confirm_subscription(
        mode: str = Query(alias="hub.mode"),
        token: str = Query(alias="hub.verify_token"),
        challenge: str = Query(alias="hub.challenge"),
    ) -> PlainTextResponse:
        if mode != "subscribe" or not hmac.compare_digest(token, webhook.verify_token):
            raise HTTPException(status_code=403, detail="not our subscription")
        return PlainTextResponse(challenge)

    @router.post("/webhook")
    async def receive_notification(request: Request) -> dict[str, int]:
        body = await request.body()
        if not signed_by_meta(webhook.app_secret, body, request.headers.get(SIGNATURE_HEADER)):
            log.warning("whatsapp_signature_refused")
            raise HTTPException(status_code=401, detail="invalid signature")
        try:
            notification = parse(json.loads(body))
        except ValueError:
            raise HTTPException(status_code=400, detail="not a notification") from None

        stored = 0
        for received in notification.messages:
            async with deps.sessions() as session:
                account = await find_channel_account(session, "whatsapp", received.phone_number_id)
            if account is None:
                # A number no tenant owns. Answering with an error would only make Meta
                # deliver the same notification again for a week.
                log.warning("whatsapp_number_unknown")
                continue
            with telemetry.span(
                "receive whatsapp",
                {"frontdesk.tenant_id": str(account.tenant_id)},
                kind=SpanKind.SERVER,
            ) as arrival:
                async with tenant_transaction(deps.sessions, account.tenant_id) as session:
                    receipt = await receive(session, account, received.message)
                arrival.set_attribute("frontdesk.conversation_id", str(receipt.conversation_id))
                arrival.set_attribute("frontdesk.duplicate", receipt.duplicate)
                stored += not receipt.duplicate
                if receipt.pending:
                    await deps.queue.send(
                        Trigger(
                            tenant_id=account.tenant_id,
                            conversation_id=receipt.conversation_id,
                            traceparent=telemetry.carried(),
                        ),
                        deduplication_id=f"{account.id}:{received.message.provider_message_id}",
                    )

        for delivery in notification.deliveries:
            if delivery.cost is None:
                continue
            async with deps.sessions() as session:
                account = await find_channel_account(session, "whatsapp", delivery.phone_number_id)
            if account is not None:
                async with tenant_transaction(deps.sessions, account.tenant_id) as session:
                    await record_charge(session, delivery.provider_message_id, delivery.cost)

        if notification.ignored:
            log.info("whatsapp_messages_ignored", extra={"count": notification.ignored})
        return {"stored": stored}

    return router
