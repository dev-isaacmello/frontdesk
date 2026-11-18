"""The owner's side of the API: what the panel's server calls on behalf of a signed-in owner.

Every request carries two proofs. The signature says it comes from the panel's server and
was not altered. The session token says which owner it is for, and through the owner which
tenant: no request names a tenant, so none can name someone else's.
"""

import asyncio
import dataclasses
import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from frontdesk import logs
from frontdesk.agent.rule_check import check_rules
from frontdesk.api.deps import ApiDeps
from frontdesk.channels.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, verify
from frontdesk.db.session import tenant_transaction
from frontdesk.domain import approvals, owners, panel, rules
from frontdesk.domain.owners import Owner
from frontdesk.domain.tenants import load_tenant
from frontdesk.domain.text import Storable
from frontdesk.queue.triggers import Trigger

SESSION_HEADER = "X-Frontdesk-Owner-Session"

log = logging.getLogger(__name__)

_RULE_CHECK_SECONDS = 20


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(_Body):
    email: Storable = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class Decision(_Body):
    approved: bool


class RulesText(_Body):
    body: Storable = Field(max_length=4000)


class OwnerMessage(_Body):
    text: Storable = Field(min_length=1, max_length=2000)


def owner_router(deps: ApiDeps) -> APIRouter:
    router = APIRouter(prefix="/owner")

    async def signed(request: Request) -> bytes:
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

    async def owner_of(request: Request) -> tuple[Owner, bytes]:
        """The owner a request is for, after its signature and its session were checked."""
        body = await signed(request)
        token = request.headers.get(SESSION_HEADER)
        if token:
            async with deps.sessions() as session:
                owner = await owners.resolve_session(session, token, deps.clock())
            if owner is not None:
                return owner, body
        raise HTTPException(status_code=401, detail="not signed in")

    def parsed[BodyT: BaseModel](model: type[BodyT], body: bytes) -> BodyT:
        try:
            return model.model_validate_json(body)
        except ValidationError:
            raise HTTPException(status_code=422, detail="invalid body") from None

    async def wake(owner: Owner, conversation_id: UUID, reason: str) -> None:
        await deps.queue.send(
            Trigger(tenant_id=owner.tenant_id, conversation_id=conversation_id),
            deduplication_id=f"owner:{reason}",
        )

    @router.post("/sessions")
    async def sign_in(request: Request) -> dict[str, Any]:
        credentials = parsed(Credentials, await signed(request))
        async with deps.sessions() as session:
            found = await owners.find_owner(session, credentials.email, credentials.password)
        if found is None:
            # One answer for an unknown e-mail and for a wrong password.
            raise HTTPException(status_code=401, detail="invalid credentials")
        owner, name = found
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            signed_in = await owners.open_session(session, owner, name, deps.clock())
            tenant = await load_tenant(session, owner.tenant_id)
        log.info("owner_signed_in", extra={"tenant_id": str(owner.tenant_id)})
        return {
            "token": signed_in.token,
            "expires_at": signed_in.expires_at,
            "owner": {"name": name},
            "tenant": {"slug": tenant.slug, "name": tenant.name},
        }

    @router.delete("/sessions", status_code=204)
    async def sign_out(request: Request) -> Response:
        owner, _ = await owner_of(request)
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            await owners.close_session(session, request.headers[SESSION_HEADER])
        return Response(status_code=204)

    @router.get("/conversations")
    async def list_conversations(request: Request) -> dict[str, Any]:
        owner, _ = await owner_of(request)
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            found = await panel.conversations(session)
            tenant = await load_tenant(session, owner.tenant_id)
        return {
            "tenant": {"slug": tenant.slug, "name": tenant.name},
            "conversations": [dataclasses.asdict(each) for each in found],
        }

    @router.get("/conversations/{conversation_id}")
    async def show_conversation(conversation_id: UUID, request: Request) -> dict[str, Any]:
        owner, _ = await owner_of(request)
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            found = await panel.conversation(session, conversation_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown conversation")
        return dataclasses.asdict(found)

    @router.post("/conversations/{conversation_id}/messages", status_code=202)
    async def answer_as_owner(conversation_id: UUID, request: Request) -> Response:
        owner, body = await owner_of(request)
        message = parsed(OwnerMessage, body)
        now = deps.clock()
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            written = await panel.say_as_owner(session, conversation_id, message.text, now)
        if not written:
            raise HTTPException(status_code=409, detail="the agent is in charge of this one")
        await wake(owner, conversation_id, f"message:{conversation_id}:{now.timestamp()}")
        return Response(status_code=202)

    @router.post("/conversations/{conversation_id}/return", status_code=204)
    async def give_back_to_agent(conversation_id: UUID, request: Request) -> Response:
        owner, _ = await owner_of(request)
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            returned = await panel.return_to_agent(session, conversation_id, deps.clock())
        if not returned:
            raise HTTPException(status_code=409, detail="not in handoff")
        return Response(status_code=204)

    @router.get("/approvals")
    async def list_approvals(request: Request) -> dict[str, Any]:
        owner, _ = await owner_of(request)
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            waiting = await panel.waiting_approvals(session)
        return {"approvals": [dataclasses.asdict(each) for each in waiting]}

    @router.post("/approvals/{approval_id}/decision", status_code=204)
    async def decide_approval(approval_id: UUID, request: Request) -> Response:
        owner, body = await owner_of(request)
        decision = parsed(Decision, body)
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            conversation_id = await approvals.decide(
                session, approval_id, approved=decision.approved, now=deps.clock()
            )
        if conversation_id is None:
            # Not theirs, not there, or already decided: one answer for all three.
            raise HTTPException(status_code=404, detail="no pending approval with that id")
        log.info(
            "approval_decided",
            extra={"tenant_id": str(owner.tenant_id), "approved": decision.approved},
        )
        await wake(owner, conversation_id, f"approval:{approval_id}")
        return Response(status_code=204)

    @router.get("/usage")
    async def show_usage(request: Request) -> dict[str, Any]:
        owner, _ = await owner_of(request)
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            tenant = await load_tenant(session, owner.tenant_id)
            return dataclasses.asdict(await panel.usage(session, tenant, deps.clock()))

    async def rules_view(owner: Owner, *, checked_by_model: bool | None) -> dict[str, Any]:
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            active = await rules.active_rules(session, owner.tenant_id)
            found = await rules.findings_of(session, owner.tenant_id)
        return {
            "version": active.version if active else 0,
            "body": active.body if active else "",
            "saved_at": active.created_at if active else None,
            "findings": [dataclasses.asdict(each) for each in found],
            "checked_by_model": checked_by_model,
        }

    @router.get("/rules")
    async def show_rules(request: Request) -> dict[str, Any]:
        owner, _ = await owner_of(request)
        return await rules_view(owner, checked_by_model=None)

    @router.put("/rules")
    async def save_rules(request: Request) -> dict[str, Any]:
        owner, body = await owner_of(request)
        text = parsed(RulesText, body)
        async with tenant_transaction(deps.sessions, owner.tenant_id) as session:
            await rules.save_rules(session, owner.tenant_id, text.body.strip(), deps.clock())
        # The version is saved and in force whatever happens below. The check only tells
        # the owner what in it will have no effect.
        return await rules_view(owner, checked_by_model=await _checked(deps, owner.tenant_id))

    return router


async def _checked(deps: ApiDeps, tenant_id: UUID) -> bool:
    """Runs the rule check within a time limit. False when the model part did not finish."""
    try:
        async with asyncio.timeout(_RULE_CHECK_SECONDS):
            await check_rules(deps.agent, tenant_id)
    except Exception as error:
        log.warning("rule_check_failed", extra={"tenant_id": str(tenant_id), **logs.failure(error)})
        await check_rules(deps.agent, tenant_id, with_model=False)
        return False
    return True
