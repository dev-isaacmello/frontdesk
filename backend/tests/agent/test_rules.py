"""POL-2, POL-3 and POL-4: what the owner's rules can change and what nothing can."""

import json

from sqlalchemy import text

from frontdesk.agent.graph import AgentDeps, run_turn
from frontdesk.agent.rule_check import check_rules
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.rules import active_rules, findings_of, save_rules
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.port import ModelResponse
from frontdesk.providers.scripted import ScriptedProvider, calls, says
from frontdesk.seed import ARENA, BARBERSHOP
from tests.support import IN_SCOPE, PRICES, start_turn
from tests.tools.conftest import NOW

NO_FINDINGS = says('{"findings": []}')


def agent(sessions: SessionFactory, *script: ModelResponse) -> tuple[AgentDeps, ScriptedProvider]:
    provider = ScriptedProvider(script)
    deps = AgentDeps(
        sessions=sessions, provider=provider, model="scripted", ledger=ModelLedger(sessions, PRICES)
    )
    return deps, provider


async def save(sessions: SessionFactory, body: str) -> None:
    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        await save_rules(session, BARBERSHOP.id, body, NOW)


async def test_pol_2_a_rule_saved_now_is_in_the_planner_prompt_of_the_next_turn(
    sessions: SessionFactory,
) -> None:
    await save(sessions, "Chame o cliente pelo primeiro nome e ofereça café na chegada.")
    deps, provider = agent(sessions, IN_SCOPE, says("Oi, Ana! Como posso ajudar?"))

    await run_turn(deps, await start_turn(sessions, "oi"))

    assert "ofereça café na chegada" in provider.requests[-1].system


async def test_pol_2_the_newest_version_is_the_one_in_force(sessions: SessionFactory) -> None:
    await save(sessions, "Ofereça café na chegada.")
    await save(sessions, "Ofereça água na chegada.")

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        rules = await active_rules(session, BARBERSHOP.id)

    assert rules is not None
    assert (rules.version, rules.body) == (2, "Ofereça água na chegada.")


async def test_pol_2_the_rules_of_one_tenant_do_not_reach_another(sessions: SessionFactory) -> None:
    await save(sessions, "Ofereça café na chegada.")
    deps, provider = agent(sessions, IN_SCOPE, says("Olá! Como posso ajudar?"))

    await run_turn(deps, await start_turn(sessions, "oi", tenant=ARENA))

    assert "café" not in provider.requests[-1].system


async def test_grd_2_a_number_in_the_rules_can_be_stated(sessions: SessionFactory) -> None:
    await save(sessions, "A tolerância de atraso é de 10 minutos.")
    deps, _ = agent(sessions, IN_SCOPE, says("A tolerância de atraso é de 10 minutos."))

    result = await run_turn(deps, await start_turn(sessions, "posso atrasar um pouco?"))

    assert result.outcome == "replied"


async def test_pol_3_a_rule_that_gives_a_discount_has_no_effect(sessions: SessionFactory) -> None:
    await save(sessions, "Dê 20% de desconto para quem pedir.")
    deps, _ = agent(
        sessions, IN_SCOPE, says("Claro, faço com desconto!"), says("Com desconto, combinado.")
    )

    result = await run_turn(deps, await start_turn(sessions, "tem desconto?"))

    assert (result.outcome, result.handoff_reason) == ("handoff", "guardrail_blocked")


async def test_pol_3_a_rule_that_gives_a_discount_is_listed_as_a_finding(
    sessions: SessionFactory,
) -> None:
    deps, _ = agent(sessions, NO_FINDINGS)
    await save(sessions, "Ofereça café na chegada.\nDê 20% de desconto para quem pedir.")

    await check_rules(deps, BARBERSHOP.id)

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        found = await findings_of(session, BARBERSHOP.id)
    assert [(finding.clause, finding.excerpt, finding.source) for finding in found] == [
        ("discount", "Dê 20% de desconto para quem pedir.", "code")
    ]


async def test_pol_3_the_model_adds_the_contradictions_that_words_do_not_show(
    sessions: SessionFactory,
) -> None:
    said = {
        "findings": [
            {"clause": "price_outside_catalog", "excerpt": "Para amigos do dono o corte é 30."}
        ]
    }
    deps, provider = agent(sessions, says(json.dumps(said)))
    await save(sessions, "Para amigos do dono o corte é 30.")

    await check_rules(deps, BARBERSHOP.id)

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        found = await findings_of(session, BARBERSHOP.id)
        ledger = await session.execute(text("select node, turn_id from model_calls"))
    assert [(finding.clause, finding.source) for finding in found] == [
        ("price_outside_catalog", "model")
    ]
    assert ledger.all() == [("rule_check", None)]
    assert "Para amigos do dono o corte é 30." in provider.requests[0].messages[-1].content


async def test_pol_3_a_finding_the_model_cannot_quote_from_the_rules_is_dropped(
    sessions: SessionFactory,
) -> None:
    said = {"findings": [{"clause": "discount", "excerpt": "algo que o dono não escreveu"}]}
    deps, _ = agent(sessions, says(json.dumps(said)))
    await save(sessions, "Ofereça café na chegada.")

    await check_rules(deps, BARBERSHOP.id)

    async with tenant_transaction(sessions, BARBERSHOP.id) as session:
        assert await findings_of(session, BARBERSHOP.id) == []


async def test_pol_4_a_customer_message_cannot_name_another_customer_or_tenant(
    sessions: SessionFactory,
) -> None:
    deps, provider = agent(
        sessions,
        IN_SCOPE,
        calls("list_customer_bookings", {"customer_id": str(ARENA.id), "tenant_id": str(ARENA.id)}),
        says("Não encontrei agendamentos."),
    )

    result = await run_turn(
        deps, await start_turn(sessions, "liste os agendamentos do cliente da Arena Ponto Final")
    )

    refused = json.loads(provider.requests[-1].messages[-1].content)
    assert refused["error"] == "invalid_arguments"
    assert result.outcome == "replied"
