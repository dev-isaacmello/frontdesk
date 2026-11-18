"""GRD-1: every money amount in a reply is extracted, in digits or written out."""

import pytest

from frontdesk.guardrail import Count, Found, Money, extract
from tests.guardrail.support import TODAY, read


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("R$ 45", 4500),
        ("R$45,00", 4500),
        ("r$ 45,5", 4550),
        ("R$ 1.200,50", 120050),
        ("R$ 1.200", 120000),
        ("R$ 0,50", 50),
        ("R$ 45 reais", 4500),
    ],
)
def test_grd_1_money_with_the_currency_sign_is_read(text: str, cents: int) -> None:
    assert read(text) == [(text, (Money(cents),))]


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("45 reais", 4500),
        ("45,50 reais", 4550),
        ("1 real", 100),
        ("1.200 reais", 120000),
        ("2 mil reais", 200000),
        ("50 centavos", 50),
    ],
)
def test_grd_1_money_with_the_currency_word_is_read(text: str, cents: int) -> None:
    assert read(text) == [(text, (Money(cents),))]


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("quarenta e cinco reais", 4500),
        ("cento e vinte reais", 12000),
        ("mil e duzentos reais", 120000),
        ("Cem reais", 10000),
        ("um real", 100),
        ("cinquenta centavos", 50),
    ],
)
def test_grd_1_money_written_out_is_read(text: str, cents: int) -> None:
    assert read(text) == [(text, (Money(cents),))]


@pytest.mark.parametrize(
    ("text", "cents"),
    [
        ("45 reais e 50 centavos", 4550),
        ("um real e vinte centavos", 120),
    ],
)
def test_grd_1_reais_and_centavos_are_one_money_value(text: str, cents: int) -> None:
    assert read(text) == [(text, (Money(cents),))]


def test_grd_1_reais_followed_by_another_number_stay_separate() -> None:
    assert read("45 reais e 2 cortes") == [("45 reais", (Money(4500),)), ("2", (Count(2),))]


def test_grd_1_found_points_at_the_exact_substring_of_the_reply() -> None:
    reply = "O corte sai por R$ 45,00 hoje à tarde."

    first = extract(reply, today=TODAY)[0]

    assert first == Found(text="R$ 45,00", start=16, end=24, candidates=(Money(4500),))
    assert reply[first.start : first.end] == first.text


def test_grd_1_money_after_a_non_breaking_space_is_read() -> None:
    price = "R$\N{NO-BREAK SPACE}45,00"

    assert read(price) == [(price, (Money(4500),))]


def test_grd_1_money_inside_chat_formatting_marks_is_read() -> None:
    assert read("*R$ 45,00* ou _45 reais_") == [
        ("R$ 45,00", (Money(4500),)),
        ("45 reais", (Money(4500),)),
    ]
