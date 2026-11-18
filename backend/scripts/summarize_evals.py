"""Builds the comparison of models from the committed runs of the golden set.

    uv run python scripts/summarize_evals.py

Writes evals/comparison.json and a copy the panel reads, web/src/data/model-comparison.json.
"""

import json
from pathlib import Path

from frontdesk.evals.comparison import compare

REPO = Path(__file__).resolve().parents[2]
TARGETS = (
    REPO / "evals" / "comparison.json",
    REPO / "web" / "src" / "data" / "model-comparison.json",
)


def main() -> None:
    runs = [
        json.loads(path.read_text()) for path in sorted((REPO / "evals" / "runs").glob("*.json"))
    ]
    models = json.loads((REPO / "evals" / "models.json").read_text())
    compared = compare(runs, models["excluded"])
    for target in TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(compared, ensure_ascii=False, indent=2) + "\n")
    for entry in compared["entries"]:
        print(
            f"{entry['model']:14} prompts {entry['prompt_version']} "
            f"passed {entry['passed_per_run']} of {entry['cases']}, "
            f"{entry['cost_per_conversation_microusd']} micro-USD per conversation, "
            f"{entry['model_ms_per_turn_p50']} ms per turn"
        )


if __name__ == "__main__":
    main()
