"""The inbound side of the web chat channel."""

import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from opentelemetry.trace import SpanKind
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from frontdesk import telemetry
from frontdesk.api.deps import ApiDeps
from frontdesk.channels.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, verify
from frontdesk.channels.webchat import ServerEvent, conversation_events
from frontdesk.db.session import tenant_transaction
from frontdesk.domain.conversations import (
    ChannelAccount,
    InboundMessage,
    belongs_to,
    find_channel_account,
    receive,
)
from frontdesk.domain.customers import ChannelIdentity
from frontdesk.queue.triggers import Trigger


class WebchatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Identifiers are compared, never cleaned: one with anything but visible ASCII is refused.
    session_id: str = Field(min_length=1, max_length=64, pattern=r"^[\x21-\x7e]+$")
    message_id: str = Field(min_length=1, max_length=64, pattern=r"^[\x21-\x7e]+$")
    text: str = Field(min_length=1, max_length=2000)
    display_name: str | None = Field(default=None, max_length=80)


class Accepted(BaseModel):
    conversation_id: UUID
    duplicate: bool


def webchat_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter(prefix="/channels/webchat/{slug}")

    async def authenticated_body(request: Request) -> bytes:
        """The raw body of a request whose signature was verified over those same bytes."""
        body = await request.body()
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        genuine = verify(
            deps.webchat_secret,
            deps.clock(),
            request.method,
            path,
            body,
            timestamp=request.headers.get(TIMESTAMP_HEADER),
            signature=request.headers.get(SIGNATURE_HEADER),
        )
        if not genuine:
            raise HTTPException(status_code=401, detail="invalid signature")
        return body

    async def account_of(slug: str) -> ChannelAccount:
        async with deps.sessions() as session:
            account = await find_channel_account(session, "webchat", slug)
        if account is None:
            raise HTTPException(status_code=404, detail="unknown tenant")
        return account

    @router.post("/messages", status_code=202)
    async def receive_message(slug: str, request: Request) -> Accepted:
        body = await authenticated_body(request)
        try:
            message = WebchatMessage.model_validate_json(body)
        except ValidationError:
            raise HTTPException(status_code=422, detail="not a web chat message") from None
        account = await account_of(slug)

        inbound = InboundMessage(
            # Scoped by session, so one visitor cannot shadow a message id of another.
            provider_message_id=f"{message.session_id}:{message.message_id}",
            sender=ChannelIdentity(
                channel="webchat",
                external_id=message.session_id,
                display_name=message.display_name,
            ),
            text=message.text,
            sent_at=deps.clock(),
            raw=message.model_dump(),
        )
        with telemetry.span(
            "receive webchat",
            {"frontdesk.tenant_id": str(account.tenant_id)},
            kind=SpanKind.SERVER,
        ) as arrival:
            async with tenant_transaction(deps.sessions, account.tenant_id) as session:
                receipt = await receive(session, account, inbound)
            arrival.set_attribute("frontdesk.conversation_id", str(receipt.conversation_id))
            arrival.set_attribute("frontdesk.duplicate", receipt.duplicate)

            # Also on a redelivery of a message that still waits: the first trigger may
            # have been lost between the commit above and the queue.
            if receipt.pending:
                await deps.queue.send(
                    Trigger(
                        tenant_id=account.tenant_id,
                        conversation_id=receipt.conversation_id,
                        traceparent=telemetry.carried(),
                    ),
                    # Scoped by account: two tenants may see the same session and message
                    # ids, and queue deduplication must not let one silence the other.
                    deduplication_id=f"{account.id}:{inbound.provider_message_id}",
                )
        return Accepted(conversation_id=receipt.conversation_id, duplicate=receipt.duplicate)

    @router.get("/conversations/{conversation_id}/events")
    async def stream_events(
        slug: str,
        conversation_id: UUID,
        request: Request,
        session_id: str = Query(min_length=1, max_length=64),
        after: UUID | None = None,
    ) -> StreamingResponse:
        await authenticated_body(request)
        account = await account_of(slug)
        # A valid signature proves the caller is the panel's server, not which visitor it
        # speaks for. The stream is opened only for the session that owns the conversation.
        async with tenant_transaction(deps.sessions, account.tenant_id) as session:
            owned = await belongs_to(session, conversation_id, account, session_id)
        if not owned:
            raise HTTPException(status_code=404, detail="unknown conversation")
        events = conversation_events(
            deps.sessions,
            deps.notifications,
            account.tenant_id,
            conversation_id,
            after=str(after) if after else None,
        )
        return StreamingResponse(
            _server_sent(events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


async def _server_sent(events: AsyncIterator[ServerEvent]) -> AsyncIterator[str]:
    async for event in events:
        if event.event == "heartbeat":
            yield ": keepalive\n\n"
            continue
        identifier = f"id: {event.id}\n" if event.id else ""
        yield f"{identifier}event: {event.event}\ndata: {json.dumps(event.data)}\n\n"
