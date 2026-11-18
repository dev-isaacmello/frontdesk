"""CST-2, CST-3 and CST-5: which model is called, and when none is."""

from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest
from sqlalchemy import text

from frontdesk.agent.graph import AgentDeps, run_turn
from frontdesk.agent.router import Routes
from frontdesk.agent.rule_check import check_rules
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.budget import ModelCallsClosedError
from frontdesk.domain.rules import save_rules
from frontdesk.providers.ledger import ModelLedger, ModelPrice, PriceTable
from frontdesk.providers.port import ModelResponse, Usage
from frontdesk.providers.scripted import ScriptedProvider, says
from frontdesk.seed import ARENA, BARBERSHOP, TenantSeed
from tests.conftest import PLAN, Database
from tests.support import IN_SCOPE, PRICES, start_turn

ROUTES = Routes(default="scripted", classify="small", pro="large", economy="cheap")
A_DOLLAR = 1_000_000


def agent(
    sessions: SessionFactory, *script: ModelResponse, cap: int | None = None
) -> tuple[AgentDeps, ScriptedProvider]:
    provider = ScriptedProvider(script)
    deps = AgentDeps(
        sessions=sessions,
        provider=provider,
        model="scripted",
        ledger=ModelLedger(sessions, PRICES),
        routes=ROUTES,
        daily_cap_microusd=cap,
    )
    return deps, provider


async def spend(sessions: SessionFactory, tenant: TenantSeed, microusd: int) -> None:
    """Model calls of that cost, made by the tenant earlier this month."""
    async with tenant_transaction(sessions, tenant.id) as session:
        await session.execute(
            text(
                """
                insert into model_calls (tenant_id, node, provider, model, input_tokens,
                    output_tokens, cache_read_tokens, cache_write_tokens, latency_ms,
                    cost_microusd, price_table_version, created_at)
                values (:tenant, 'plan', 'scripted', 'scripted', 0, 0, 0, 0, 0, :cost, 'test', :at)
                """
            ),
            {"tenant": tenant.id, "cost": microusd, "at": datetime(2026, 11, 10, 12, 0)},  # noqa: DTZ001
        )


async def models_called(provider: ScriptedProvider) -> list[str]:
    return [request.model for request in provider.requests]


async def test_cst_2_each_node_is_answered_by_the_model_its_route_names(
    sessions: SessionFactory,
) -> None:
    deps, provider = agent(sessions, IN_SCOPE, says("Oi! Como posso ajudar?"))

    await run_turn(deps, await start_turn(sessions, "oi"))

    assert await models_called(provider) == ["small", "scripted"]


async def test_cst_2_a_tenant_on_the_pro_plan_is_planned_by_the_larger_model(
    sessions: SessionFactory,
) -> None:
    deps, provider = agent(sessions, IN_SCOPE, says("Olá! Quer reservar uma quadra?"))

    await run_turn(deps, await start_turn(sessions, "oi", tenant=ARENA))

    assert await models_called(provider) == ["small", "large"]


def test_cst_2_with_no_rule_every_call_goes_to_the_default_model() -> None:
    plain = Routes(default="only")

    assert plain.model_for("classify", "basic", "normal") == "only"
    assert plain.model_for("plan", "pro", "economy") == "only"


async def test_cst_3_a_tenant_at_its_budget_is_served_by_the_cheaper_model(
    sessions: SessionFactory,
) -> None:
    await spend(sessions, BARBERSHOP, 5 * A_DOLLAR)
    deps, provider = agent(sessions, IN_SCOPE, says("Oi! Como posso ajudar?"))

    result = await run_turn(deps, await start_turn(sessions, "oi"))

    assert result.outcome == "replied"
    assert await models_called(provider) == ["cheap", "cheap"]


async def test_cst_3_a_tenant_well_past_its_budget_is_served_by_a_person_only(
    sessions: SessionFactory,
) -> None:
    # The barbershop's budget is USD 5 a month; a quarter past it, no model is called.
    await spend(sessions, BARBERSHOP, 6_250_000)
    deps, provider = agent(sessions)

    result = await run_turn(deps, await start_turn(sessions, "oi"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "budget_exhausted")
    assert provider.requests == []


async def test_cst_3_what_one_tenant_spent_does_not_count_against_another(
    sessions: SessionFactory,
) -> None:
    await spend(sessions, BARBERSHOP, 50 * A_DOLLAR)
    deps, provider = agent(sessions, IN_SCOPE, says("Olá! Quer reservar uma quadra?"))

    result = await run_turn(deps, await start_turn(sessions, "oi", tenant=ARENA))

    assert result.outcome == "replied"
    assert await models_called(provider) == ["small", "large"]


async def test_cst_5_the_daily_cap_counts_every_tenant_and_stops_model_calls(
    sessions: SessionFactory,
) -> None:
    costly = PriceTable(
        version="test",
        models={"scripted": ModelPrice(input=Decimal(A_DOLLAR), output=Decimal(A_DOLLAR))},
    )
    ledger = ModelLedger(sessions, costly)
    spent = ModelResponse(
        text="x",
        stop_reason="end",
        usage=Usage(input_tokens=1, output_tokens=1),
        model="scripted",
        latency_ms=0,
    )
    await ledger.record(
        tenant_id=ARENA.id, turn_id=None, node="plan", provider="scripted", response=spent
    )
    deps, provider = agent(sessions, cap=2 * A_DOLLAR)

    result = await run_turn(deps, await start_turn(sessions, "oi"))

    # One call of one input and one output token at a dollar each, by the other tenant.
    assert (result.outcome, result.handoff_reason) == ("handoff", "budget_exhausted")
    assert provider.requests == []


async def test_cst_5_under_the_cap_the_turn_runs(sessions: SessionFactory) -> None:
    deps, _ = agent(sessions, IN_SCOPE, says("Oi! Como posso ajudar?"), cap=2 * A_DOLLAR)

    result = await run_turn(deps, await start_turn(sessions, "oi"))

    assert result.outcome == "replied"


async def test_cst_5_model_calls_can_be_switched_off_by_hand(
    sessions: SessionFactory, database: Database
) -> None:
    with psycopg.connect(database.superuser_dsn, dbname=PLAN.database) as connection:
        connection.execute("update system_flags set enabled = false where name = 'model_calls'")
    deps, provider = agent(sessions)

    result = await run_turn(deps, await start_turn(sessions, "oi"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "budget_exhausted")
    assert provider.requests == []


async def test_cst_5_the_application_role_cannot_flip_the_switch(sessions: SessionFactory) -> None:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        changed = await session.execute(
            text("select has_table_privilege(current_user, 'system_flags', 'update')")
        )

    assert changed.scalar() is False


async def test_cst_5_the_review_of_the_owners_rules_is_a_model_call_and_stops_too(
    sessions: SessionFactory, database: Database
) -> None:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        await save_rules(
            session, BARBERSHOP.id, "Seja simpático.", datetime(2026, 11, 18, 13, 0, tzinfo=UTC)
        )
    with psycopg.connect(database.superuser_dsn, dbname=PLAN.database) as connection:
        connection.execute("update system_flags set enabled = false where name = 'model_calls'")
    deps, provider = agent(sessions)

    with pytest.raises(ModelCallsClosedError):
        await check_rules(deps, BARBERSHOP.id)

    # What the code finds by itself is still reported, with no model.
    assert await check_rules(deps, BARBERSHOP.id, with_model=False) == []
    assert provider.requests == []
