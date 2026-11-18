"""EVAL-5: a run is refused when its estimate passes what is left of the budget.

What was spent is read from the result files of earlier runs, which are committed. So the
budget is a property of the repository and not of the machine that happens to run.
"""

import json
from pathlib import Path

DEFAULT_TURN_MICROUSD = 2_500
"""What a turn is assumed to cost before a model has a measured run of its own."""

_MARGIN = 1.5


def spent(runs: Path) -> int:
    """Micro-USD spent by every run recorded in the directory and the ones below it."""
    return sum(
        json.loads(path.read_text())["totals"]["cost_microusd"] for path in runs.rglob("*.json")
    )


def estimate(runs: Path, model: str, turns: int) -> int:
    """What a run of that many turns is expected to cost, with half as much again.

    The cost per turn is the one measured in the newest run of the same model, when there
    is one.
    """
    measured = [
        run["totals"]["cost_microusd"] / run["totals"]["turns"]
        for run in (json.loads(path.read_text()) for path in sorted(runs.glob("*.json")))
        if run["model"] == model and run["totals"]["turns"]
    ]
    per_turn = measured[-1] if measured else DEFAULT_TURN_MICROUSD
    return round(per_turn * turns * _MARGIN)


def allows(runs: Path, models: list[str], turns: int, cap_microusd: int) -> tuple[bool, int, int]:
    """Whether the planned run fits. Also returns what was spent and what the run should cost."""
    already = spent(runs)
    planned = sum(estimate(runs, model, turns) for model in models)
    return already + planned <= cap_microusd, already, planned
