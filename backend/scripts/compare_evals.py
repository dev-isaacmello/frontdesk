"""Compares a golden set run with the baseline of main. Exit code 1 when the gate fails.

uv run python scripts/compare_evals.py --run /tmp/run.json --report /tmp/report.md
"""

import argparse
import json
import sys
from pathlib import Path

from frontdesk.evals.gate import compare

REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--baseline", type=Path, default=REPO / "evals" / "baseline.json")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--report", type=Path, help="where to write the markdown report")
    arguments = parser.parse_args()

    verdict = compare(
        json.loads(arguments.baseline.read_text()), json.loads(arguments.run.read_text())
    )
    if arguments.report:
        arguments.report.write_text(verdict.report)
    print(verdict.report)
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
