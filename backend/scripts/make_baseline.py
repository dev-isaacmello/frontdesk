"""Writes evals/baseline.json from the committed runs of one model with the current prompts.

    uv run python scripts/make_baseline.py --model gpt-oss-120b

Run on main after the runs it should stand on were made. A pull request is compared with
this file.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from frontdesk.agent import prompts
from frontdesk.evals.gate import baseline_from

REPO = Path(__file__).resolve().parents[2]
MINIMUM_RUNS = 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", required=True)
    arguments = parser.parse_args()

    current = hashlib.sha256(Path(prompts.__file__).read_bytes()).hexdigest()[:12]
    runs = [
        run
        for run in (
            json.loads(path.read_text())
            for path in sorted((REPO / "evals" / "runs").glob("*.json"))
        )
        if run["model"] == arguments.model and run["prompt_version"] == current
    ]
    if len(runs) < MINIMUM_RUNS:
        print(
            f"{len(runs)} runs of {arguments.model} with prompts {current}; {MINIMUM_RUNS} needed"
        )
        return 1
    baseline = baseline_from(runs)
    target = REPO / "evals" / "baseline.json"
    target.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n")
    totals = baseline["totals"]
    print(f"{len(runs)} runs: {totals['passed']} of {totals['cases']} cases pass in every one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
