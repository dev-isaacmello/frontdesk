"""The golden set and its runner, with a scripted model in place of a real one."""

import json
from pathlib import Path

from frontdesk.db.session import SessionFactory
from frontdesk.evals import budget, golden
from frontdesk.providers.port import ModelResponse
from frontdesk.providers.scripted import calls, says
from frontdesk.seed import BARBERSHOP
from tests.support import IN_SCOPE, RecordingSender, scripted_worker

GOLDEN = Path(__file__).resolve().parents[3] / "evals" / "golden" / "cases.json"
CORTE = BARBERSHOP.service_id("Corte")
QUOTE = calls("quote", {"service_ids": [str(CORTE)], "starts_at": "2026-11-18T14:00:00"})


def environment(sessions: SessionFactory, *script: ModelResponse) -> golden.Environment:
    deps, _ = scripted_worker(sessions, RecordingSender(), *script)

    async def nothing_to_reset() -> None:
        """The test database is emptied by the fixture that precedes every test."""

    return golden.Environment(sessions=sessions, worker=lambda _now: deps, reset=nothing_to_reset)


def the_case(chosen: golden.GoldenSet, case_id: str) -> golden.Case:
    return next(case for case in chosen.cases if case.id == case_id)


def test_eval_1_the_set_is_versioned_and_covers_what_the_spec_names() -> None:
    chosen = golden.load(GOLDEN)

    assert chosen.version == "2026-11-18.3"
    assert len({case.id for case in chosen.cases}) == len(chosen.cases) == 41
    assert {case.category for case in chosen.cases} == {
        "tools",
        "history",
        "arguments",
        "numbers",
        "policy",
        "refusal",
        "injection",
        "approval",
        "handoff",
        "knowledge",
    }


async def test_eval_2_a_case_passes_when_the_conversation_ends_as_it_should(
    sessions: SessionFactory,
) -> None:
    chosen = golden.load(GOLDEN)
    env = environment(sessions, IN_SCOPE, QUOTE, says("O corte custa R$ 45,00."))

    result = await golden.run_case(env, the_case(chosen, "price-of-one-service"), chosen.now)

    [turn] = result.turns
    assert (result.passed, result.failures) == (True, [])
    assert (turn.outcome, turn.tools, turn.model_calls) == ("replied", ["quote"], 3)


async def test_eval_2_a_case_that_fails_says_why(sessions: SessionFactory) -> None:
    chosen = golden.load(GOLDEN)
    env = environment(sessions, IN_SCOPE, says("Temos corte e barba. Qual você prefere?"))

    result = await golden.run_case(env, the_case(chosen, "price-of-one-service"), chosen.now)

    assert result.passed is False
    assert result.failures == [
        "called none of the expected tools",
        "reply does not state {'money': 4500}",
    ]


async def test_eval_2_what_is_in_the_schedule_is_part_of_the_verdict(
    sessions: SessionFactory,
) -> None:
    chosen = golden.load(GOLDEN)
    env = environment(sessions, IN_SCOPE, says("Pode deixar, já anotei aqui."))

    result = await golden.run_case(env, the_case(chosen, "booking-in-one-message"), chosen.now)

    assert "the expected booking is not in the schedule" in result.failures


async def test_eval_2_a_case_that_cannot_run_is_a_failed_case_not_a_crash(
    sessions: SessionFactory,
) -> None:
    chosen = golden.load(GOLDEN)
    env = environment(sessions)

    result = await golden.run_case(env, the_case(chosen, "price-of-one-service"), chosen.now)

    assert (result.passed, result.failures) == (False, ["error: ScriptExhaustedError"])


def run_file(directory: Path, name: str, model: str, cost: int, turns: int) -> None:
    document = {"model": model, "totals": {"cost_microusd": cost, "turns": turns}}
    (directory / name).write_text(json.dumps(document))


def test_eval_5_a_run_is_refused_when_its_estimate_passes_what_is_left(tmp_path: Path) -> None:
    run_file(tmp_path, "1-a.json", "model-a", cost=4_000_000, turns=40)

    # 40 turns at the measured 100,000 each, with half as much again: 6,000,000.
    fits, already, planned = budget.allows(tmp_path, ["model-a"], turns=40, cap_microusd=5_000_000)

    assert (fits, already, planned) == (False, 4_000_000, 6_000_000)


def test_eval_5_a_model_never_run_is_estimated_at_the_default_cost(tmp_path: Path) -> None:
    run_file(tmp_path, "1-a.json", "model-a", cost=100_000, turns=40)

    # 2,500 a turn by default, 40 turns, with half as much again.
    fits, already, planned = budget.allows(tmp_path, ["model-b"], turns=40, cap_microusd=5_000_000)

    assert (fits, already, planned) == (True, 100_000, 150_000)
