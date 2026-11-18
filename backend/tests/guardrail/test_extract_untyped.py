"""GRD-3: a numeric expression that cannot be typed exactly is found with no candidates."""

import datetime

import pytest

from frontdesk.guardrail import Count, Day
from tests.guardrail.support import read


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("Posso dar 20% de desconto", "20%"),
        ("20 % de desconto", "20 %"),
        ("vinte por cento", "vinte por cento"),
        ("4,5% a mais", "4,5%"),
    ],
)
def test_grd_3_a_percentage_is_untyped(text: str, value: str) -> None:
    assert read(text) == [(value, ())]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("nota 4,5", "4,5"),
        ("45,00", "45,00"),
        ("nota 4.5", "4.5"),
        ("dois e meio", "dois e meio"),
        ("\N{VULGAR FRACTION ONE HALF} hora", "\N{VULGAR FRACTION ONE HALF}"),
    ],
)
def test_grd_3_a_fraction_that_is_not_money_is_untyped(text: str, value: str) -> None:
    assert read(text) == [(value, ())]


@pytest.mark.parametrize(
    "text",
    [
        "51 99999-0000",
        "(51) 99999-0000",
        "+55 51 99999-0000",
        "3333-4444",
        "123.456.789-00",
        "90000-000",
        "2026-11-20",
        "9:00-18:00",
        "192.168.0.1",
    ],
)
def test_grd_3_digit_runs_with_separators_that_are_no_date_or_money_are_untyped(text: str) -> None:
    assert read(text) == [(text, ())]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("uns 40 e poucos reais", "40 e poucos reais"),
        ("quarenta e poucos", "quarenta e poucos"),
        ("R$ 40 e pouco", "R$ 40 e pouco"),
        ("R$ 1,5 mil", "R$ 1,5 mil"),
        ("2 milhões", "2 milhões"),
        ("R$ 40-50", "R$ 40-50"),
    ],
)
def test_grd_3_an_approximation_or_range_is_untyped(text: str, value: str) -> None:
    assert read(text) == [(value, ())]


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("R$ 45.00", "R$ 45.00"),
        ("R$ 45,123", "R$ 45,123"),
        ("45,50 centavos", "45,50"),
    ],
)
def test_grd_3_money_in_a_shape_that_is_not_brazilian_is_untyped(text: str, value: str) -> None:
    assert read(text) == [(value, ())]


@pytest.mark.parametrize("text", ["25:00", "14:75", "31/02", "20/13", "31/02/2026"])
def test_grd_3_a_time_or_date_that_does_not_exist_is_untyped(text: str) -> None:
    assert read(text) == [(text, ())]


def test_grd_3_a_date_with_a_month_that_lacks_the_day_is_untyped() -> None:
    assert read("31 de fevereiro") == [("31 de fevereiro", ())]


def test_grd_3_an_hour_that_does_not_fit_the_period_is_untyped() -> None:
    assert read("3 da noite") == [("3 da noite", ())]


@pytest.mark.parametrize("text", ["3kg", "10km", "30m", "4K", "1º"])
def test_grd_3_a_number_glued_to_an_unknown_unit_is_untyped(text: str) -> None:
    assert read(text) == [(text, ())]


def test_grd_3_a_phone_does_not_swallow_the_values_around_it() -> None:
    values = read("Ligue 51 99999-0000 até sexta ou mande 2 fotos")

    assert [text for text, _ in values] == ["51 99999-0000", "sexta", "2"]
    assert values[0][1] == ()
    assert values[1][1] == (Day(datetime.date(2026, 11, 20)),)
    assert values[2][1] == (Count(2),)
