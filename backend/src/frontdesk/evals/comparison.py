"""EVAL-4: the runs of the golden set, side by side, per model and per version of the prompts.

A model does not answer the same way twice, so one run is an anecdote. Runs of the same
model with the same prompts are grouped: the cases passed in each run are listed, and a
case that passes in some runs and fails in others is named as unstable instead of being
averaged away.
"""

import statistics
from typing import Any


def compare(runs: list[dict[str, Any]], excluded: list[dict[str, str]]) -> dict[str, Any]:
    """One entry per model and prompt version, the newest prompts of each model first."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for run in sorted(runs, key=lambda each: each["ran_at"]):
        groups.setdefault((run["model"], run["prompt_version"]), []).append(run)
    entries = [_entry(model, prompts, group) for (model, prompts), group in groups.items()]
    entries.sort(key=lambda entry: (entry["model"], entry["last_run_at"]), reverse=True)
    return {
        "golden_version": max(run["golden_version"] for run in runs),
        "entries": entries,
        "excluded": excluded,
    }


def _entry(model: str, prompts: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    totals = [run["totals"] for run in runs]
    outcomes: dict[str, list[bool]] = {}
    for run in runs:
        for case in run["cases"]:
            outcomes.setdefault(case["id"], []).append(case["passed"])
    categories: dict[str, dict[str, float]] = {}
    for name in totals[0]["by_category"]:
        passed = [each["by_category"][name]["passed"] for each in totals]
        categories[name] = {
            "cases": totals[0]["by_category"][name]["cases"],
            "passed_mean": round(statistics.mean(passed), 1),
        }
    return {
        "model": model,
        "prompt_version": prompts,
        "runs": len(runs),
        "last_run_at": runs[-1]["ran_at"],
        "cases": totals[0]["cases"],
        "passed_per_run": [each["passed"] for each in totals],
        "passed_mean": round(statistics.mean(each["passed"] for each in totals), 1),
        "cost_per_conversation_microusd": round(
            statistics.mean(each["cost_per_conversation_microusd"] for each in totals)
        ),
        "model_ms_per_turn_p50": round(
            statistics.median(each["model_ms_per_turn_p50"] for each in totals)
        ),
        "blocked_drafts_mean": round(statistics.mean(each["blocked_drafts"] for each in totals), 1),
        "by_category": categories,
        "always_failing": sorted(case for case, seen in outcomes.items() if not any(seen)),
        "unstable": sorted(case for case, seen in outcomes.items() if any(seen) and not all(seen)),
    }
