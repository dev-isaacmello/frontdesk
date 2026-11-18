"""EVAL-3: compares a run of the golden set with the baseline of main and decides.

A real model does not answer the same way twice, so the baseline is made of several runs
on main and holds a case as passing only when it passed in every one of them. The gate
fails on those cases, not on a rate: each one that fails in the pull request is named in
the report. One is tolerated, two are not. Cost is reported and never fails the gate.
"""

import statistics
from dataclasses import dataclass
from typing import Any

ALLOWED_NEW_FAILURES = 1
_COST_WORTH_A_NOTE = 1.3


@dataclass(frozen=True)
class Verdict:
    passed: bool
    report: str
    """Markdown, for the pull request."""


def baseline_from(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """The baseline of several runs of one model with one version of the prompts.

    It has the shape of a run, so that it is compared like one. A case passes in it only
    if it passed in every run.
    """
    first = runs[0]
    outcomes: dict[str, list[bool]] = {}
    for run in runs:
        for case in run["cases"]:
            outcomes.setdefault(case["id"], []).append(case["passed"])
    cases = [
        {"id": case_id, "passed": all(seen), "failures": []} for case_id, seen in outcomes.items()
    ]
    totals = [run["totals"] for run in runs]
    return {
        "model": first["model"],
        "prompt_version": first["prompt_version"],
        "golden_version": first["golden_version"],
        "runs": len(runs),
        "cases": cases,
        "totals": {
            "cases": len(cases),
            "passed": sum(case["passed"] for case in cases),
            "cost_per_conversation_microusd": round(
                statistics.mean(each["cost_per_conversation_microusd"] for each in totals)
            ),
            "model_ms_per_turn_p50": round(
                statistics.median(each["model_ms_per_turn_p50"] for each in totals)
            ),
            "blocked_drafts": round(statistics.mean(each["blocked_drafts"] for each in totals)),
        },
    }


def compare(baseline: dict[str, Any], run: dict[str, Any]) -> Verdict:
    before = {case["id"]: case for case in baseline["cases"]}
    after = {case["id"]: case for case in run["cases"]}
    broken = sorted(
        case_id
        for case_id, case in after.items()
        if not case["passed"] and before.get(case_id, {}).get("passed", False)
    )
    fixed = sorted(
        case_id
        for case_id, case in after.items()
        if case["passed"] and case_id in before and not before[case_id]["passed"]
    )
    passed = len(broken) <= ALLOWED_NEW_FAILURES
    was, now = baseline["totals"], run["totals"]

    cost_now, cost_was = (totals["cost_per_conversation_microusd"] for totals in (now, was))
    lines = [
        f"### Golden set: {'passed' if passed else 'failed'}",
        "",
        f"Model `{run['model']}`, golden set `{run['golden_version']}`, "
        f"prompts `{run['prompt_version']}` against `{baseline['prompt_version']}` on main.",
        "",
        f"- Cases passed: {now['passed']} of {now['cases']} "
        f"(passing in every run on main: {was['passed']} of {was['cases']}).",
        f"- Cost per conversation: {_usd(cost_now)} (main: {_usd(cost_was)}).",
        f"- Model time per turn, median: {now['model_ms_per_turn_p50']} ms "
        f"(main: {was['model_ms_per_turn_p50']} ms).",
        f"- Drafts the checks refused: {now['blocked_drafts']} (main: {was['blocked_drafts']}).",
    ]
    if broken:
        lines += ["", "Pass in every run on main and fail here:"]
        lines += [f"- `{case_id}`: {'; '.join(after[case_id]['failures'])}" for case_id in broken]
    if fixed:
        lines += ["", "Failed on main and pass here: " + ", ".join(f"`{each}`" for each in fixed)]
    if cost_now > cost_was * _COST_WORTH_A_NOTE:
        lines += [
            "",
            "The cost per conversation grew by more than 30%. This does not fail the gate.",
        ]
    if not passed:
        lines += [
            "",
            f"The gate tolerates {ALLOWED_NEW_FAILURES} case that passes in every run on main "
            f"and fails here, since a model does not answer the same way twice. "
            f"There are {len(broken)}.",
        ]
    return Verdict(passed, "\n".join(lines) + "\n")


def _usd(microusd: int) -> str:
    return f"USD {microusd / 1_000_000:.4f}"
