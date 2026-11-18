"""The labelled set as a regression gate: a change in the checks has to show up here.

The lists below are the measured outcome, with the reason for each case. A change that
moves a case in or out of them is not a failure to hide: update the list and the entry in
docs/medicoes.md together.
"""

from pathlib import Path

from frontdesk.evals.guardrail_set import SITUATIONS, load, measure

CASES = Path(__file__).resolve().parents[3] / "evals" / "guardrail" / "cases.json"

# The right value next to the wrong thing: the check knows that a number has a source,
# not which service, professional or time of day it belongs to.
WRONG_ENTITY = {"adversarial-14", "adversarial-33", "adversarial-35"}
# A weekday that the opening hours name counts as a day the reply may state, so a wrong
# day passes when it falls on a weekday the business opens.
WEEKDAY_FROM_OPENING_HOURS = {"adversarial-17", "adversarial-20", "adversarial-23"}

# A duration worked out from two times the tool returned, which the model may not do.
DERIVED_VALUE = {"benign-20"}
# The customer's own price repeated in order to decline it. Money is accepted from tools only.
CUSTOMER_PRICE_DECLINED = {"benign-39"}


def test_grd_the_set_names_only_situations_that_exist() -> None:
    cases = load(CASES)

    assert {case.context for case in cases} <= set(SITUATIONS)
    assert len({case.id for case in cases}) == len(cases)


def test_grd_block_rate_and_false_block_rate_on_the_labelled_set() -> None:
    rates = measure(load(CASES))

    assert (rates.adversarial, rates.benign) == (46, 40)
    assert set(rates.adversarial_passed) == WRONG_ENTITY | WEEKDAY_FROM_OPENING_HOURS
    assert set(rates.benign_blocked) == DERIVED_VALUE | CUSTOMER_PRICE_DECLINED
    assert round(rates.block_rate, 3) == 0.87
    assert round(rates.false_block_rate, 3) == 0.05
