"""EVAL-4: runs of the golden set grouped by model and prompts, with their variance shown."""

from typing import Any

from frontdesk.evals.comparison import compare


def run(model: str, prompts: str, at: str, passing: set[str], cost: int, ms: int) -> dict[str, Any]:
    cases = [{"id": each, "passed": each in passing} for each in ("a", "b", "c", "d")]
    return {
        "model": model,
        "prompt_version": prompts,
        "golden_version": "v1",
        "ran_at": at,
        "cases": cases,
        "totals": {
            "cases": 4,
            "passed": len(passing),
            "cost_per_conversation_microusd": cost,
            "model_ms_per_turn_p50": ms,
            "blocked_drafts": 1,
            "by_category": {"tools": {"cases": 4, "passed": len(passing)}},
        },
    }


def test_eval_4_runs_of_one_model_and_one_prompt_are_one_entry_with_their_spread() -> None:
    runs = [
        run("small", "p1", "2026-11-18T01:00:00", {"a", "b", "c"}, cost=1000, ms=7000),
        run("small", "p1", "2026-11-18T02:00:00", {"a", "b"}, cost=1200, ms=8000),
        run("small", "p1", "2026-11-18T03:00:00", {"a", "b", "c"}, cost=1100, ms=9000),
    ]

    [entry] = compare(runs, [])["entries"]

    assert entry["passed_per_run"] == [3, 2, 3]
    assert entry["passed_mean"] == 2.7
    assert (entry["cost_per_conversation_microusd"], entry["model_ms_per_turn_p50"]) == (1100, 8000)
    assert (entry["unstable"], entry["always_failing"]) == (["c"], ["d"])
    assert entry["by_category"] == {"tools": {"cases": 4, "passed_mean": 2.7}}


def test_eval_4_a_change_of_prompts_is_a_separate_entry_and_the_newest_comes_first() -> None:
    runs = [
        run("small", "before", "2026-11-18T01:00:00", {"a"}, cost=1000, ms=7000),
        run("small", "after", "2026-11-18T05:00:00", {"a", "b"}, cost=1000, ms=7000),
        run("other", "after", "2026-11-18T06:00:00", {"a"}, cost=500, ms=2000),
    ]
    left_out = [{"model": "tiny", "reason": "does not call tools"}]

    compared = compare(runs, left_out)

    assert [(each["model"], each["prompt_version"]) for each in compared["entries"]] == [
        ("small", "after"),
        ("small", "before"),
        ("other", "after"),
    ]
    assert compared["excluded"] == left_out
