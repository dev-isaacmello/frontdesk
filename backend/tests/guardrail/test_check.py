"""GRD-2 and GRD-3: a reply passes only when each value has a typed match from an allowed origin."""

import datetime

import pytest

from frontdesk.guardrail import (
    Count,
    Day,
    Duration,
    Fact,
    Money,
    Origin,
    Sourced,
    TimeOfDay,
    Verdict,
    Violation,
    check,
    facts_in,
)
from tests.guardrail.support import TODAY

TOMORROW = datetime.date(2026, 11, 18)
PRICE_REPLY = "O corte sai por R$ 45,00 e leva 30 minutos."
SLOTS_REPLY = "Tenho horário amanhã às 10h ou às 11h30."
SLOTS_LEDGER = (
    Sourced(Day(TOMORROW), "tool"),
    Sourced(TimeOfDay(10, 0), "tool"),
    Sourced(TimeOfDay(11, 30), "tool"),
)


def test_grd_2_a_reply_whose_values_are_all_in_the_ledger_passes() -> None:
    ledger = [Sourced(Money(4500), "tool"), Sourced(Duration(30), "tool")]

    verdict = check(PRICE_REPLY, ledger, today=TODAY)

    assert verdict == Verdict(violations=())
    assert verdict.passed


def test_grd_2_a_price_different_from_the_ledger_fails_on_that_price() -> None:
    ledger = [Sourced(Money(4000), "tool"), Sourced(Duration(30), "tool")]

    verdict = check(PRICE_REPLY, ledger, today=TODAY)

    assert not verdict.passed
    assert verdict.violations == (
        Violation(text="R$ 45,00", reason="no_origin", candidates=(Money(4500),)),
    )


def test_grd_2_a_day_and_both_times_in_the_ledger_pass() -> None:
    assert check(SLOTS_REPLY, SLOTS_LEDGER, today=TODAY).passed


@pytest.mark.parametrize(
    ("missing", "blocked"),
    [(0, "amanhã"), (1, "10h"), (2, "11h30")],
)
def test_grd_2_each_value_missing_from_the_ledger_fails_on_its_own(
    missing: int, blocked: str
) -> None:
    ledger = [sourced for index, sourced in enumerate(SLOTS_LEDGER) if index != missing]

    verdict = check(SLOTS_REPLY, ledger, today=TODAY)

    assert [violation.text for violation in verdict.violations] == [blocked]


@pytest.mark.parametrize("origin", ["customer", "profile", "rules", "knowledge"])
def test_grd_2_a_price_passes_only_when_it_came_from_a_tool(origin: Origin) -> None:
    verdict = check("Fica R$ 45.", [Sourced(Money(4500), origin)], today=TODAY)

    assert verdict.violations == (
        Violation(text="R$ 45", reason="no_origin", candidates=(Money(4500),)),
    )


def test_grd_2_a_price_from_a_tool_passes_even_if_the_customer_also_said_it() -> None:
    ledger = [Sourced(Money(4500), "customer"), Sourced(Money(4500), "tool")]

    assert check("Fica R$ 45.", ledger, today=TODAY).passed


@pytest.mark.parametrize("origin", ["tool", "customer", "profile", "rules", "knowledge"])
@pytest.mark.parametrize(
    ("reply", "fact"),
    [
        ("Pode ser às 15h.", TimeOfDay(15, 0)),
        ("Fica para amanhã.", Day(TOMORROW)),
        ("Leva 30 minutos.", Duration(30)),
        ("Reservei 2 quadras.", Count(2)),
    ],
)
def test_grd_2_times_days_durations_and_counts_pass_from_any_origin(
    reply: str, fact: Fact, origin: Origin
) -> None:
    assert check(reply, [Sourced(fact, origin)], today=TODAY).passed


@pytest.mark.parametrize(
    ("reply", "fact"),
    [
        ("Leva 30 minutos.", Money(3000)),
        ("Leva 30 minutos.", Count(30)),
        ("Leva 30 minutos.", TimeOfDay(0, 30)),
        ("Fica R$ 30.", Duration(30)),
        ("Fica R$ 30.", Count(30)),
        ("Fica R$ 30.", Money(30)),
        ("Temos 30 vagas.", Duration(30)),
        ("Temos 30 vagas.", Money(3000)),
        ("Às 15h.", Count(15)),
        ("Às 15h.", TimeOfDay(15, 30)),
        ("Fica para amanhã.", Day(TODAY)),
    ],
)
def test_grd_2_the_same_number_of_another_type_or_value_does_not_validate(
    reply: str, fact: Fact
) -> None:
    verdict = check(reply, [Sourced(fact, "tool")], today=TODAY)

    assert [violation.reason for violation in verdict.violations] == ["no_origin"]


@pytest.mark.parametrize("fact", [Duration(120), TimeOfDay(2, 0)])
def test_grd_2_an_ambiguous_value_passes_with_either_reading_in_the_ledger(fact: Fact) -> None:
    assert check("Fica 2 horas.", [Sourced(fact, "tool")], today=TODAY).passed


def test_grd_2_a_value_narrowed_by_context_needs_that_reading() -> None:
    verdict = check("Começa às 2 horas.", [Sourced(Duration(120), "tool")], today=TODAY)

    assert verdict.violations == (
        Violation(text="2 horas", reason="no_origin", candidates=(TimeOfDay(2, 0),)),
    )


def test_grd_3_a_percentage_blocks_the_reply_as_untyped() -> None:
    ledger = [Sourced(Count(20), "tool"), Sourced(Money(2000), "tool")]

    verdict = check("Posso dar 20% de desconto", ledger, today=TODAY)

    assert not verdict.passed
    assert verdict.violations == (Violation(text="20%", reason="untyped", candidates=()),)


def test_grd_3_a_value_with_an_empty_ledger_blocks_the_reply() -> None:
    verdict = check("Abrimos às 9h.", [], today=TODAY)

    assert verdict.violations == (
        Violation(text="9h", reason="no_origin", candidates=(TimeOfDay(9, 0),)),
    )


def test_grd_3_violations_come_in_order_of_appearance() -> None:
    reply = "Custa R$ 50, uns 20% a menos, e leva 40 minutos."

    verdict = check(reply, [], today=TODAY)

    assert [(violation.text, violation.reason) for violation in verdict.violations] == [
        ("R$ 50", "no_origin"),
        ("20%", "untyped"),
        ("40 minutos", "no_origin"),
    ]


def test_grd_3_a_reply_without_values_passes_with_an_empty_ledger() -> None:
    verdict = check("Tenho uma opção para você", [], today=TODAY)

    assert verdict.passed
    assert verdict.violations == ()


def test_grd_2_the_ledger_can_be_any_iterable_read_once() -> None:
    ledger = (sourced for sourced in [Sourced(Money(4500), "tool"), Sourced(Duration(30), "tool")])

    assert check(PRICE_REPLY, ledger, today=TODAY).passed


def test_grd_2_facts_in_tags_every_candidate_of_every_value_with_the_origin() -> None:
    message = "quero amanhã às 15h, pode ser 2 horas?"

    assert facts_in(message, "customer", today=TODAY) == [
        Sourced(Day(TOMORROW), "customer"),
        Sourced(TimeOfDay(15, 0), "customer"),
        Sourced(Duration(120), "customer"),
        Sourced(TimeOfDay(2, 0), "customer"),
    ]


def test_grd_2_a_price_the_customer_asked_for_does_not_validate_the_reply() -> None:
    ledger = facts_in("faz por 30 reais amanhã?", "customer", today=TODAY)

    verdict = check("Fechado, R$ 30 amanhã.", ledger, today=TODAY)

    assert [violation.text for violation in verdict.violations] == ["R$ 30"]


def test_grd_2_an_opening_time_from_the_owner_rules_validates_the_reply() -> None:
    ledger = facts_in("Aberto de terça a sábado, das 9h às 19h.", "rules", today=TODAY)

    assert check("Abrimos às 9h e fechamos às 19h.", ledger, today=TODAY).passed
