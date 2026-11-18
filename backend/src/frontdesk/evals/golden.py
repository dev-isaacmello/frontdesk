"""Runs the golden set: real conversations through the real worker, judged by code.

A case is a short conversation with what has to be true at its end: which tools were
called, what the last reply states, what is in the schedule. Every expectation is checked
deterministically, against the reply read by the same extractor the guardrail uses and
against the database. Nothing here asks a model whether a model did well.
"""

import datetime as dt
import json
import logging
import re
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.bookings import Booked
from frontdesk.domain.conversations import InboundMessage, find_channel_account, receive
from frontdesk.domain.customers import ChannelIdentity, identify_customer
from frontdesk.domain.rules import save_rules
from frontdesk.guardrail import Fact, Money, TimeOfDay, extract
from frontdesk.queue.triggers import Trigger
from frontdesk.seed import TENANTS, TenantSeed
from frontdesk.tools.bookings import CreateBookingInput, create_booking
from frontdesk.tools.context import ToolContext
from frontdesk.worker.handler import WorkerDeps, handle

OTHER_CUSTOMER = "Bruno"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    tenant: TenantSeed
    setup: dict[str, Any]
    turns: list[str]
    expect: dict[str, Any]


@dataclass(frozen=True)
class GoldenSet:
    version: str
    now: dt.datetime
    cases: list[Case]


@dataclass(frozen=True)
class TurnRecord:
    said: str
    outcome: str | None
    reply: str | None
    tools: list[str]
    blocked_drafts: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    model_ms: int
    cost_microusd: int


@dataclass(frozen=True)
class CaseResult:
    id: str
    category: str
    passed: bool
    failures: list[str]
    turns: list[TurnRecord] = field(default_factory=list)


@dataclass(frozen=True)
class Environment:
    sessions: SessionFactory
    worker: Callable[[dt.datetime], WorkerDeps]
    """Builds the worker for a case, with its clock fixed at the instant of the set."""
    reset: Callable[[], Awaitable[None]]
    """Empties everything a conversation writes, keeping the seeded tenants."""


def load(path: Path) -> GoldenSet:
    document = json.loads(path.read_text())
    tenants = {tenant.slug: tenant for tenant in TENANTS}
    return GoldenSet(
        version=document["version"],
        now=dt.datetime.fromisoformat(document["now"]),
        cases=[
            Case(
                id=item["id"],
                category=item["category"],
                tenant=tenants[item["tenant"]],
                setup=item["setup"],
                turns=item["turns"],
                expect=item["expect"],
            )
            for item in document["cases"]
        ],
    )


async def run_case(env: Environment, case: Case, now: dt.datetime) -> CaseResult:
    await env.reset()
    sender = f"eval-{case.id}"
    try:
        await _prepare(env, case, sender, now)
        turns = [
            await _turn(env, case, sender, index, said, now)
            for index, said in enumerate(case.turns)
        ]
        failures = await _failures(env, case, sender, turns, now)
    except Exception as error:
        # A case that cannot run is a failed case, with the reason, not a crashed suite.
        log.exception("case_could_not_run", extra={"case": case.id})
        return CaseResult(case.id, case.category, False, [f"error: {type(error).__name__}"])
    return CaseResult(case.id, case.category, not failures, failures, turns)


TRANSIENT = frozenset(
    f"error: {name}"
    for name in ("ModelUnavailableError", "ModelTimeoutError", "ModelThrottledError")
)
"""Failures of the road to the model, not of the model. A case that ends in one is run again."""


def interrupted(result: CaseResult) -> bool:
    return bool(TRANSIENT & set(result.failures))


def summary(results: list[CaseResult]) -> dict[str, Any]:
    turns = [turn for result in results for turn in result.turns]
    answered = [turn.model_ms for turn in turns if turn.model_calls]
    by_category: dict[str, dict[str, int]] = {}
    for result in results:
        tally = by_category.setdefault(result.category, {"cases": 0, "passed": 0})
        tally["cases"] += 1
        tally["passed"] += result.passed
    cost = sum(turn.cost_microusd for turn in turns)
    return {
        "cases": len(results),
        "passed": sum(result.passed for result in results),
        "pass_rate": round(sum(result.passed for result in results) / len(results), 3),
        # Cases that could not run to their end. A run with any of these is not a measure.
        "errors": sum(any(f.startswith("error:") for f in result.failures) for result in results),
        "turns": len(turns),
        "model_calls": sum(turn.model_calls for turn in turns),
        "input_tokens": sum(turn.input_tokens for turn in turns),
        "output_tokens": sum(turn.output_tokens for turn in turns),
        "cost_microusd": cost,
        "cost_per_conversation_microusd": round(cost / len(results)),
        "model_ms_per_turn_p50": round(statistics.median(answered)) if answered else 0,
        "model_ms_per_turn_p95": round(_percentile(answered, 0.95)) if answered else 0,
        "blocked_drafts": sum(turn.blocked_drafts for turn in turns),
        "by_category": dict(sorted(by_category.items())),
    }


def as_document(results: list[CaseResult]) -> list[dict[str, Any]]:
    return [asdict(result) for result in results]


def _percentile(values: list[int], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(fraction * (len(ordered) - 1)))]


async def _prepare(env: Environment, case: Case, sender: str, now: dt.datetime) -> None:
    tenant = case.tenant
    for wanted in case.setup.get("bookings", []):
        who = sender if wanted["customer"] == "self" else OTHER_CUSTOMER
        identity = ChannelIdentity(channel="webchat", external_id=who, display_name=who)
        async with tenant_transaction(env.sessions, tenant.id) as session:
            customer_id = await identify_customer(session, tenant.id, identity)
            context = ToolContext(
                tenant_id=tenant.id,
                customer_id=customer_id,
                # Placed well before the case runs, so that no booking rule about notice
                # stands between the set and the situation it wants to start from.
                now=now - dt.timedelta(days=2),
                idempotency_key=f"setup:{case.id}:{wanted['starts_at']}:{who}",
            )
            placed = await create_booking.run(
                context,
                CreateBookingInput(
                    service_id=tenant.service_id(wanted["service"]),
                    resource_id=tenant.resource_id(wanted["resource"]),
                    starts_at=dt.datetime.fromisoformat(wanted["starts_at"]),
                ),
                session,
            )
        if not isinstance(placed, Booked):
            raise RuntimeError(f"setup booking refused in case {case.id}")
    if "rules" in case.setup:
        async with tenant_transaction(env.sessions, tenant.id) as session:
            await save_rules(session, tenant.id, case.setup["rules"], now)


async def _turn(
    env: Environment, case: Case, sender: str, index: int, said: str, now: dt.datetime
) -> TurnRecord:
    tenant = case.tenant
    async with env.sessions() as session:
        account = await find_channel_account(session, "webchat", tenant.slug)
    assert account is not None
    message = InboundMessage(
        provider_message_id=f"{sender}:{index}",
        sender=ChannelIdentity(channel="webchat", external_id=sender, display_name="Cliente"),
        text=said,
        sent_at=now,
        raw={"text": said},
    )
    async with tenant_transaction(env.sessions, tenant.id) as session:
        receipt = await receive(session, account, message)
    await handle(env.worker(now), Trigger(tenant.id, receipt.conversation_id))
    return await _record(env, tenant, receipt.conversation_id, said)


async def _record(
    env: Environment, tenant: TenantSeed, conversation_id: UUID, said: str
) -> TurnRecord:
    async with tenant_transaction(env.sessions, tenant.id) as session:
        turn = (
            await session.execute(
                text(
                    "select id, outcome, blocked_drafts from turns "
                    "where conversation_id = :c order by id desc limit 1"
                ),
                {"c": conversation_id},
            )
        ).one()
        reply = await session.scalar(
            text(
                "select body from messages where turn_id = :t and direction = 'out' "
                "order by seq desc limit 1"
            ),
            {"t": turn.id},
        )
        planned = await session.scalars(
            text("select detail from turn_steps where turn_id = :t and node = 'plan' order by seq"),
            {"t": turn.id},
        )
        tools = [tool for detail in planned for tool in detail.get("tools", [])]
        spent = (
            await session.execute(
                text(
                    "select count(*), coalesce(sum(input_tokens + cache_read_tokens), 0), "
                    "coalesce(sum(output_tokens), 0), coalesce(sum(latency_ms), 0), "
                    "coalesce(sum(cost_microusd), 0) from model_calls where turn_id = :t"
                ),
                {"t": turn.id},
            )
        ).one()
    return TurnRecord(
        said=said,
        outcome=turn.outcome,
        reply=reply,
        tools=tools,
        blocked_drafts=turn.blocked_drafts,
        model_calls=spent[0],
        input_tokens=int(spent[1]),
        output_tokens=int(spent[2]),
        model_ms=int(spent[3]),
        cost_microusd=int(spent[4]),
    )


async def _failures(
    env: Environment, case: Case, sender: str, turns: list[TurnRecord], now: dt.datetime
) -> list[str]:
    expect, last = case.expect, turns[-1]
    reply = last.reply or ""
    called = {tool for turn in turns for tool in turn.tools}
    today = now.astimezone(ZoneInfo(case.tenant.timezone)).date()
    stated = {found for value in extract(reply, today=today) for found in value.candidates}
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    check(last.outcome in expect["outcome"], f"outcome was {last.outcome}")
    for tool in expect.get("tools", []):
        check(tool in called, f"did not call {tool}")
    if "any_tool" in expect:
        check(bool(called & set(expect["any_tool"])), "called none of the expected tools")
    for wanted in expect.get("states", []):
        check(_fact(wanted) in stated, f"reply does not state {wanted}")
    if "states_any" in expect:
        options = {_fact(wanted) for wanted in expect["states_any"]}
        check(bool(options & stated), "reply states none of the accepted values")
    for unwanted in expect.get("not_states", []):
        check(_fact(unwanted) not in stated, f"reply states {unwanted}")
    if "matches" in expect:
        check(re.search(expect["matches"], reply) is not None, "reply lacks the expected wording")
    if "not_matches" in expect:
        check(re.search(expect["not_matches"], reply) is None, "reply has forbidden wording")

    schedule = await _schedule(env, case.tenant, sender)
    if "own_bookings" in expect:
        check(
            len(schedule["own"]) == expect["own_bookings"], f"own bookings: {len(schedule['own'])}"
        )
    if "others_bookings" in expect:
        found = len(schedule["others"])
        check(found == expect["others_bookings"], f"bookings of others: {found}")
    if "booking" in expect:
        wanted = expect["booking"]
        key = (wanted["service"], wanted["resource"], wanted["starts_at"])
        check(key in schedule["own"], "the expected booking is not in the schedule")
    if "approval_pending" in expect:
        check(schedule["approval_pending"] == expect["approval_pending"], "approval state differs")
    return failures


def _fact(wanted: dict[str, Any]) -> Fact:
    if "money" in wanted:
        return Money(wanted["money"])
    hour, minute = wanted["time"].split(":")
    return TimeOfDay(int(hour), int(minute))


async def _schedule(env: Environment, tenant: TenantSeed, sender: str) -> dict[str, Any]:
    zone = ZoneInfo(tenant.timezone)
    async with tenant_transaction(env.sessions, tenant.id) as session:
        rows = await session.execute(
            text(
                """
                select s.name, r.name, lower(b.during), i.external_id
                from bookings b
                join services s on s.id = b.service_id
                join resources r on r.id = b.resource_id
                join customer_identities i on i.customer_id = b.customer_id
                where b.status = 'confirmed'
                """
            )
        )
        pending = await session.scalar(
            text("select count(*) from approval_requests where status = 'pending'")
        )
    own: list[tuple[str, str, str]] = []
    others: list[tuple[str, str, str]] = []
    for service, resource, starts_at, external_id in rows:
        entry = (service, resource, starts_at.astimezone(zone).strftime("%Y-%m-%dT%H:%M"))
        (own if external_id == sender else others).append(entry)
    return {"own": own, "others": others, "approval_pending": bool(pending)}
