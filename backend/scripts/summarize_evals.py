"""Builds the comparison of models from the committed runs of the golden set.

    uv run python scripts/summarize_evals.py

Writes evals/comparison.json and a copy the panel reads, web/src/data/model-comparison.json.
The runs in which the classifier went to another deployment are summarized apart, in
evals/routing.json.
"""

import json
from pathlib import Path
from typing import Any

from frontdesk.evals.comparison import compare

REPO = Path(__file__).resolve().parents[2]
TARGETS = (
    REPO / "evals" / "comparison.json",
    REPO / "web" / "src" / "data" / "model-comparison.json",
)


def load(folder: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text()) for path in sorted(folder.glob("*.json"))]


def routed(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per planner, classifier and prompts, with the classifier named."""
    entries = []
    for classifier in sorted({run["classify_model"] for run in runs}):
        same = [run for run in runs if run["classify_model"] == classifier]
        entries += [
            {"classify_model": classifier, **entry} for entry in compare(same, [])["entries"]
        ]
    return entries


def describe(entry: dict[str, Any]) -> str:
    return (
        f"prompts {entry['prompt_version']} "
        f"passed {entry['passed_per_run']} of {entry['cases']}, "
        f"{entry['cost_per_conversation_microusd']} micro-USD per conversation, "
        f"{entry['model_ms_per_turn_p50']} ms per turn"
    )


def main() -> None:
    runs = load(REPO / "evals" / "runs")
    models = json.loads((REPO / "evals" / "models.json").read_text())
    compared = compare(runs, models["excluded"])
    for target in TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(compared, ensure_ascii=False, indent=2) + "\n")
    for entry in compared["entries"]:
        print(f"{entry['model']:14} {describe(entry)}")

    with_routes = routed(load(REPO / "evals" / "runs" / "routing"))
    if with_routes:
        target = REPO / "evals" / "routing.json"
        target.write_text(json.dumps({"entries": with_routes}, ensure_ascii=False, indent=2) + "\n")
        for entry in with_routes:
            who = f"{entry['model']} planning, {entry['classify_model']} classifying"
            print(f"{who}: {describe(entry)}")


if __name__ == "__main__":
    main()
