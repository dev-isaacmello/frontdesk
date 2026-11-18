"""Prints the block rate and the false block rate of the reply checks on the labelled set.

uv run python scripts/guardrail_rates.py
"""

import json
from pathlib import Path

from frontdesk.evals.guardrail_set import load, measure

CASES = Path(__file__).resolve().parents[2] / "evals" / "guardrail" / "cases.json"


def main() -> None:
    rates = measure(load(CASES))
    print(
        json.dumps(
            {
                "adversarial_cases": rates.adversarial,
                "block_rate": round(rates.block_rate, 3),
                "adversarial_that_passed": rates.adversarial_passed,
                "benign_cases": rates.benign,
                "false_block_rate": round(rates.false_block_rate, 3),
                "benign_that_were_blocked": rates.benign_blocked,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
