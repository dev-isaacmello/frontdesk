"""EVAL-3: the comparison that lets a pull request through or stops it."""

from typing import Any

from frontdesk.evals.gate import baseline_from, compare


def run(passing: list[str], failing: list[str], cost: int = 1500) -> dict[str, Any]:
    cases = [{"id": each, "passed": True, "failures": []} for each in passing]
    cases += [
        {"id": each, "passed": False, "failures": ["outcome was handoff"]} for each in failing
    ]
    return {
        "model": "gpt-5-mini",
        "golden_version": "v1",
        "prompt_version": "abc",
        "cases": cases,
        "totals": {
            "cases": len(cases),
            "passed": len(passing),
            "cost_per_conversation_microusd": cost,
            "model_ms_per_turn_p50": 7000,
            "blocked_drafts": 0,
        },
    }


def test_eval_3_a_run_like_main_passes() -> None:
    verdict = compare(run(["a", "b", "c"], []), run(["a", "b", "c"], []))

    assert verdict.passed
    assert "Cases passed: 3 of 3 (passing in every run on main: 3 of 3)" in verdict.report


def test_eval_3_one_case_lost_is_tolerated_and_named() -> None:
    verdict = compare(run(["a", "b", "c"], []), run(["a", "b"], ["c"]))

    assert verdict.passed
    assert "`c`: outcome was handoff" in verdict.report


def test_eval_3_two_cases_lost_fail_the_gate() -> None:
    verdict = compare(run(["a", "b", "c"], []), run(["a"], ["b", "c"]))

    assert not verdict.passed
    assert "### Golden set: failed" in verdict.report
    assert "There are 2." in verdict.report


def test_eval_3_a_case_that_already_failed_on_main_is_not_held_against_the_change() -> None:
    verdict = compare(run(["a"], ["b", "c"]), run(["a"], ["b", "c"]))

    assert verdict.passed


def test_eval_3_a_case_fixed_and_a_higher_cost_are_reported_without_failing() -> None:
    verdict = compare(run(["a"], ["b"], cost=1000), run(["a", "b"], [], cost=1400))

    assert verdict.passed
    assert "Failed on main and pass here: `b`" in verdict.report
    assert "grew by more than 30%" in verdict.report


def test_eval_3_the_baseline_holds_a_case_as_passing_only_if_every_run_passed_it() -> None:
    baseline = baseline_from(
        [run(["a", "b", "c"], [], cost=1000), run(["a", "b"], ["c"], cost=2000)]
    )

    assert [(case["id"], case["passed"]) for case in baseline["cases"]] == [
        ("a", True),
        ("b", True),
        ("c", False),
    ]
    assert (baseline["runs"], baseline["totals"]["passed"]) == (2, 2)
    assert baseline["totals"]["cost_per_conversation_microusd"] == 1500


def test_eval_3_a_case_that_is_unstable_on_main_cannot_fail_a_pull_request() -> None:
    baseline = baseline_from([run(["a", "b", "c"], []), run(["a"], ["b", "c"])])

    verdict = compare(baseline, run(["a"], ["b", "c"]))

    assert verdict.passed
