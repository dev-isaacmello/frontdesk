"""The reply is checked before it is sent: numbers, discounts and claimed actions."""

from frontdesk.agent.graph import AgentDeps, TurnLimits, run_turn
from frontdesk.agent.prompts import HANDOFF_NOTICE
from frontdesk.db.session import SessionFactory
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.port import ModelResponse
from frontdesk.providers.scripted import ScriptedProvider, calls, says
from frontdesk.seed import BARBERSHOP
from tests.support import IN_SCOPE, PRICES, start_turn

CORTE = BARBERSHOP.service_id("Corte")
CAIO = BARBERSHOP.resource_id("Caio")
QUOTE = ("quote", {"service_ids": [str(CORTE)], "starts_at": "2026-11-18T14:00:00"})
BOOKING = (
    "create_booking",
    {"service_id": str(CORTE), "resource_id": str(CAIO), "starts_at": "2026-11-19T10:00:00"},
)


def agent(sessions: SessionFactory, *script: ModelResponse) -> tuple[AgentDeps, ScriptedProvider]:
    provider = ScriptedProvider(script)
    deps = AgentDeps(
        sessions=sessions, provider=provider, model="scripted", ledger=ModelLedger(sessions, PRICES)
    )
    return deps, provider


async def test_grd_2_a_price_that_a_tool_returned_is_sent(sessions: SessionFactory) -> None:
    deps, _ = agent(sessions, IN_SCOPE, calls(*QUOTE), says("O corte sai por R$ 45,00."))

    result = await run_turn(deps, await start_turn(sessions, "quanto custa o corte?"))

    assert (result.outcome, result.reply) == ("replied", "O corte sai por R$ 45,00.")


async def test_grd_4_a_price_no_tool_returned_sends_the_draft_back_with_the_value_named(
    sessions: SessionFactory,
) -> None:
    deps, provider = agent(
        sessions,
        IN_SCOPE,
        says("O corte sai por R$ 40,00."),
        calls(*QUOTE),
        says("O corte sai por R$ 45,00."),
    )

    result = await run_turn(deps, await start_turn(sessions, "quanto custa o corte?"))

    correction = provider.requests[2].messages[-1]
    assert (result.outcome, result.reply) == ("replied", "O corte sai por R$ 45,00.")
    assert correction.role == "user"
    assert "R$ 40,00" in correction.content


async def test_grd_4_a_second_block_ends_in_handoff(sessions: SessionFactory) -> None:
    deps, provider = agent(
        sessions, IN_SCOPE, says("O corte sai por R$ 40,00."), says("Desculpe: R$ 42,00.")
    )

    result = await run_turn(deps, await start_turn(sessions, "quanto custa o corte?"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "guardrail_blocked")
    assert result.reply == HANDOFF_NOTICE
    assert len(provider.requests) == 3


async def test_grd_2_a_price_the_customer_said_is_not_a_source(sessions: SessionFactory) -> None:
    deps, _ = agent(sessions, IN_SCOPE, says("Isso, R$ 30,00."), says("Isso mesmo, R$ 30,00."))

    result = await run_turn(deps, await start_turn(sessions, "o corte é R$ 30,00, né?"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "guardrail_blocked")


async def test_grd_2_a_time_the_customer_said_can_be_repeated_back(
    sessions: SessionFactory,
) -> None:
    deps, _ = agent(sessions, IN_SCOPE, says("Às 15h de qual dia?"))

    result = await run_turn(deps, await start_turn(sessions, "tem horário às 15h?"))

    assert (result.outcome, result.reply) == ("replied", "Às 15h de qual dia?")


async def test_grd_2_opening_hours_come_from_the_tenant_profile(sessions: SessionFactory) -> None:
    deps, provider = agent(sessions, IN_SCOPE, says("Abrimos de terça a sábado, das 9h às 19h."))

    result = await run_turn(deps, await start_turn(sessions, "que horas vocês abrem?"))

    assert result.outcome == "replied"
    assert "terça-feira: das 09:00 às 19:00" in provider.requests[-1].system
    assert "segunda-feira: fechado" in provider.requests[-1].system


async def test_pol_1_a_discount_is_never_stated(sessions: SessionFactory) -> None:
    deps, _ = agent(
        sessions,
        IN_SCOPE,
        says("Para você eu faço com desconto!"),
        says("Tudo bem, a barba sai de graça."),
    )

    result = await run_turn(deps, await start_turn(sessions, "tem desconto pra cliente antigo?"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "guardrail_blocked")


async def test_pol_1_declining_a_discount_is_sent(sessions: SessionFactory) -> None:
    deps, _ = agent(sessions, IN_SCOPE, says("Não trabalhamos com desconto. Quer agendar?"))

    result = await run_turn(deps, await start_turn(sessions, "tem desconto pra cliente antigo?"))

    assert result.outcome == "replied"


async def test_grd_6_a_booking_claimed_without_a_tool_is_blocked(sessions: SessionFactory) -> None:
    deps, _ = agent(
        sessions, IN_SCOPE, says("Pronto, agendei seu corte!"), says("Está agendado, pode vir.")
    )

    result = await run_turn(deps, await start_turn(sessions, "marca um corte pra mim"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "guardrail_blocked")


async def test_grd_6_a_booking_a_tool_made_can_be_announced(sessions: SessionFactory) -> None:
    deps, _ = agent(
        sessions,
        IN_SCOPE,
        calls(*BOOKING),
        says("Pronto, agendei seu corte com o Caio amanhã às 10h. Fica R$ 45,00."),
    )

    result = await run_turn(
        deps, await start_turn(sessions, "marca corte com o Caio amanhã às 10h")
    )

    assert result.outcome == "replied"


async def test_agt_3_a_correction_does_not_get_around_the_limit_of_model_calls(
    sessions: SessionFactory,
) -> None:
    deps, provider = agent(sessions, IN_SCOPE, says("O corte sai por R$ 40,00."))
    limited = AgentDeps(
        sessions=deps.sessions,
        provider=deps.provider,
        model=deps.model,
        ledger=deps.ledger,
        limits=TurnLimits(model_calls=2),
    )

    result = await run_turn(limited, await start_turn(sessions, "quanto custa o corte?"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "turn_limit")
    assert len(provider.requests) == 2


async def test_grd_7_an_empty_draft_goes_back_once_and_then_to_a_person(
    sessions: SessionFactory,
) -> None:
    deps, provider = agent(sessions, IN_SCOPE, says(""), says("   "))

    result = await run_turn(deps, await start_turn(sessions, "ola"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "guardrail_blocked")
    assert result.reply == HANDOFF_NOTICE
    assert "vazia" in provider.requests[2].messages[-1].content


async def test_grd_7_a_garbled_draft_is_written_again(sessions: SessionFactory) -> None:
    deps, _ = agent(
        sessions, IN_SCOPE, says("Seu ... ​ ... Sorry ... ?\n\n\n…\n```\nOops … / ?"), says("Oi!")
    )

    result = await run_turn(deps, await start_turn(sessions, "ola"))

    assert (result.outcome, result.reply, result.blocks) == ("replied", "Oi!", 1)
