"""GRD-1 to GRD-3 as properties: what the formatters write, the guardrail reads and checks."""

import datetime
from itertools import pairwise

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from frontdesk.guardrail import Duration, Fact, Sourced, TimeOfDay, check, extract
from tests.guardrail.formatters import (
    Phrase,
    count_phrases,
    day_phrases,
    duration_phrases,
    money_phrases,
    phrases,
    phrases_of_the_same_type,
    time_phrases,
)

EXAMPLES = settings(max_examples=400, deadline=None)
TODAYS = st.dates(datetime.date(2024, 1, 1), datetime.date(2035, 12, 31))
# Plain words between values: none of them is a preposition or a unit the parser gives meaning to.
JOINERS = st.sampled_from([" ou ", " mais ", " com ", " também ", " para "])
MINUTES_IN_A_DAY = 24 * 60


def assert_recovered(phrase: Phrase, today: datetime.date) -> None:
    found = extract(phrase.text, today=today)

    assert len(found) == 1, found
    assert phrase.fact in found[0].candidates
    assert phrase.text[found[0].start : found[0].end] == found[0].text


@EXAMPLES
@given(money_phrases(), TODAYS)
def test_grd_1_any_rendered_money_is_recovered(phrase: Phrase, today: datetime.date) -> None:
    assert_recovered(phrase, today)


@EXAMPLES
@given(time_phrases(), TODAYS)
def test_grd_1_any_rendered_time_is_recovered(phrase: Phrase, today: datetime.date) -> None:
    assert_recovered(phrase, today)


@EXAMPLES
@given(st.data(), TODAYS)
def test_grd_1_any_rendered_day_is_recovered(data: st.DataObject, today: datetime.date) -> None:
    assert_recovered(data.draw(day_phrases(today)), today)


@EXAMPLES
@given(duration_phrases(), TODAYS)
def test_grd_1_any_rendered_duration_is_recovered(phrase: Phrase, today: datetime.date) -> None:
    assert_recovered(phrase, today)


@EXAMPLES
@given(count_phrases(), TODAYS)
def test_grd_1_any_rendered_count_is_recovered(phrase: Phrase, today: datetime.date) -> None:
    assert_recovered(phrase, today)


@EXAMPLES
@given(
    st.text(alphabet=st.sampled_from("0123456789 .,:/-%$()+\nRhxeº°às"), max_size=40)
    | st.text(max_size=40),
    TODAYS,
)
def test_grd_3_any_text_is_read_without_error_into_ordered_exact_spans(
    text: str, today: datetime.date
) -> None:
    found = extract(text, today=today)

    assert all(text[value.start : value.end] == value.text for value in found)
    assert all(value.start < value.end for value in found)
    assert all(before.end <= after.start for before, after in pairwise(found))


def sentence(parts: list[Phrase], joiners: list[str]) -> str:
    text = parts[0].text
    for joiner, part in zip(joiners, parts[1:], strict=True):
        text += joiner + part.text
    return f"Temos {text}."


@st.composite
def turns(draw: st.DrawFn) -> tuple[datetime.date, list[Phrase], list[str]]:
    today = draw(TODAYS)
    parts = draw(st.lists(phrases(today), min_size=1, max_size=6))
    joiners = draw(st.lists(JOINERS, min_size=len(parts) - 1, max_size=len(parts) - 1))
    return today, parts, joiners


@EXAMPLES
@given(turns())
def test_grd_2_a_text_built_only_from_ledger_facts_passes(
    turn: tuple[datetime.date, list[Phrase], list[str]],
) -> None:
    today, parts, joiners = turn
    ledger = [Sourced(part.fact, "tool") for part in parts]

    verdict = check(sentence(parts, joiners), ledger, today=today)

    assert verdict.passed, verdict.violations


def other_readings(fact: Fact) -> set[Fact]:
    """The second reading an hour expression has under the ambiguity rule, worked out by hand."""
    if isinstance(fact, TimeOfDay):
        return {Duration(fact.hour * 60 + fact.minute)}
    if isinstance(fact, Duration) and fact.minutes < MINUTES_IN_A_DAY:
        return {TimeOfDay(fact.minutes // 60, fact.minutes % 60)}
    return set()


@EXAMPLES
@given(turns(), st.data())
def test_grd_3_changing_one_value_to_one_outside_the_ledger_fails_on_it(
    turn: tuple[datetime.date, list[Phrase], list[str]], data: st.DataObject
) -> None:
    today, parts, joiners = turn
    ledger_facts = {part.fact for part in parts}
    position = data.draw(st.integers(0, len(parts) - 1))
    intruder = data.draw(phrases_of_the_same_type(parts[position].fact, today))
    assume(intruder.fact not in ledger_facts)
    assume(ledger_facts.isdisjoint(other_readings(intruder.fact)))
    changed = [*parts[:position], intruder, *parts[position + 1 :]]

    verdict = check(
        sentence(changed, joiners), [Sourced(fact, "tool") for fact in ledger_facts], today=today
    )

    assert not verdict.passed
    [violation] = verdict.violations
    assert violation.reason == "no_origin"
    assert intruder.fact in violation.candidates
    assert violation.text in intruder.text
