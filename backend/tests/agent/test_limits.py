"""AGT-3: a turn stops at fixed limits and goes to a person instead of failing."""

from frontdesk.agent.graph import AgentDeps, TurnLimits, run_turn
from frontdesk.db.session import SessionFactory
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.port import ModelResponse
from frontdesk.providers.scripted import ScriptedProvider, calls, says
from tests.support import IN_SCOPE, PRICES, start_turn

GENEROUS = TurnLimits(tool_rounds=50, model_calls=50, tokens=10_000_000)


def agent(
    sessions: SessionFactory, limits: TurnLimits, *script: ModelResponse
) -> tuple[AgentDeps, ScriptedProvider]:
    provider = ScriptedProvider(script)
    deps = AgentDeps(
        sessions=sessions,
        provider=provider,
        model="scripted",
        ledger=ModelLedger(sessions, PRICES),
        limits=limits,
    )
    return deps, provider


def lists_services() -> ModelResponse:
    return calls("list_services", {})


async def test_agt_3_a_turn_that_keeps_calling_tools_goes_to_a_person(
    sessions: SessionFactory,
) -> None:
    limits = TurnLimits(tool_rounds=2, model_calls=50, tokens=10_000_000)
    deps, provider = agent(
        sessions, limits, IN_SCOPE, lists_services(), lists_services(), lists_services()
    )

    result = await run_turn(deps, await start_turn(sessions, "quais serviços vocês têm?"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "turn_limit")
    # One classification and two plans. The third plan, already scripted, was never asked for.
    assert len(provider.requests) == 3


async def test_agt_3_a_turn_stops_at_its_limit_of_model_calls(sessions: SessionFactory) -> None:
    limits = TurnLimits(tool_rounds=50, model_calls=2, tokens=10_000_000)
    deps, provider = agent(sessions, limits, IN_SCOPE, lists_services(), lists_services())

    result = await run_turn(deps, await start_turn(sessions, "quais serviços vocês têm?"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "turn_limit")
    assert len(provider.requests) == 2


async def test_agt_3_a_turn_stops_at_its_limit_of_tokens(sessions: SessionFactory) -> None:
    # Each scripted call reports 100 input and 20 output tokens, so two calls reach 240.
    limits = TurnLimits(tool_rounds=50, model_calls=50, tokens=240)
    deps, provider = agent(sessions, limits, IN_SCOPE, lists_services(), lists_services())

    result = await run_turn(deps, await start_turn(sessions, "quais serviços vocês têm?"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "turn_limit")
    assert len(provider.requests) == 2


async def test_agt_3_a_turn_inside_its_limits_is_answered(sessions: SessionFactory) -> None:
    deps, _ = agent(sessions, GENEROUS, IN_SCOPE, lists_services(), says("Temos corte e barba."))

    result = await run_turn(deps, await start_turn(sessions, "quais serviços vocês têm?"))

    assert (result.outcome, result.reply) == ("replied", "Temos corte e barba.")
