"""GRD-1: every date in a reply is extracted and resolved against today (Tuesday 2026-11-17)."""

import datetime

import pytest

from frontdesk.guardrail import Day, extract
from tests.guardrail.support import read


def day(year: int, month: int, day_of_month: int) -> tuple[Day]:
    return (Day(datetime.date(year, month, day_of_month)),)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hoje", day(2026, 11, 17)),
        ("amanhã", day(2026, 11, 18)),
        ("amanha", day(2026, 11, 18)),
        ("Amanhã", day(2026, 11, 18)),
        ("depois de amanhã", day(2026, 11, 19)),
        ("ontem", day(2026, 11, 16)),
        ("anteontem", day(2026, 11, 15)),
    ],
)
def test_grd_1_relative_days_are_resolved(text: str, expected: tuple[Day]) -> None:
    assert read(text) == [(text, expected)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("quarta", day(2026, 11, 18)),
        ("sexta", day(2026, 11, 20)),
        ("sexta-feira", day(2026, 11, 20)),
        ("sexta feira", day(2026, 11, 20)),
        ("sábado", day(2026, 11, 21)),
        ("sabado", day(2026, 11, 21)),
        ("aos sábados", day(2026, 11, 21)),
        ("domingo", day(2026, 11, 22)),
        ("segunda", day(2026, 11, 23)),
        ("terça", day(2026, 11, 24)),
        ("terca-feira", day(2026, 11, 24)),
    ],
)
def test_grd_1_a_weekday_is_the_nearest_one_strictly_after_today(
    text: str, expected: tuple[Day]
) -> None:
    [(_, candidates)] = read(text)

    assert candidates == expected


@pytest.mark.parametrize("text", ["hoje, terça-feira", "hoje (terça)", "hoje é terça"])
def test_grd_1_the_weekday_of_today_after_hoje_is_today(text: str) -> None:
    assert [candidates for _, candidates in read(text)] == [day(2026, 11, 17), day(2026, 11, 17)]


def test_grd_1_another_weekday_after_hoje_is_still_the_next_one() -> None:
    assert read("hoje ou sexta") == [("hoje", day(2026, 11, 17)), ("sexta", day(2026, 11, 20))]


def test_grd_1_the_weekday_of_today_listed_after_hoje_is_the_next_one() -> None:
    assert read("hoje e terça") == [("hoje", day(2026, 11, 17)), ("terça", day(2026, 11, 24))]
    assert read("Hoje não. Terça eu consigo") == [
        ("Hoje", day(2026, 11, 17)),
        ("Terça", day(2026, 11, 24)),
    ]


def test_grd_1_two_weekdays_joined_by_a_hyphen_are_both_read() -> None:
    assert read("terça-sábado") == [("terça", day(2026, 11, 24)), ("sábado", day(2026, 11, 21))]


@pytest.mark.parametrize("text", ["próxima sexta", "sexta que vem", "sexta da semana que vem"])
def test_grd_1_a_weekday_said_to_be_next_is_this_week_or_the_following(text: str) -> None:
    [(_, candidates)] = read(text)

    assert candidates == (Day(datetime.date(2026, 11, 20)), Day(datetime.date(2026, 11, 27)))


@pytest.mark.parametrize(
    ("text", "value", "expected"),
    [
        ("dia 20", "20", day(2026, 11, 20)),
        ("dia 17", "17", day(2026, 11, 17)),
        ("dia 10", "10", day(2026, 12, 10)),
        ("dia 31", "31", day(2026, 12, 31)),
        ("dia vinte", "vinte", day(2026, 11, 20)),
        ("dia primeiro", "primeiro", day(2026, 12, 1)),
    ],
)
def test_grd_1_a_day_of_the_month_is_the_nearest_on_or_after_today(
    text: str, value: str, expected: tuple[Day]
) -> None:
    assert read(text) == [(value, expected)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20/11", day(2026, 11, 20)),
        ("17/11", day(2026, 11, 17)),
        ("05/01", day(2027, 1, 5)),
        ("16/11", day(2027, 11, 16)),
        ("29/02", day(2028, 2, 29)),
        ("20/11/2026", day(2026, 11, 20)),
        ("20/11/26", day(2026, 11, 20)),
        ("1/3/2025", day(2025, 3, 1)),
    ],
)
def test_grd_1_a_numeric_date_is_day_then_month(text: str, expected: tuple[Day]) -> None:
    assert read(text) == [(text, expected)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("20 de novembro", day(2026, 11, 20)),
        ("3 de março", day(2027, 3, 3)),
        ("3 de marco", day(2027, 3, 3)),
        ("vinte de novembro", day(2026, 11, 20)),
        ("20 de novembro de 2026", day(2026, 11, 20)),
        ("20 de Novembro de 2025", day(2025, 11, 20)),
        ("1º de dezembro", day(2026, 12, 1)),
        ("primeiro de dezembro", day(2026, 12, 1)),
    ],
)
def test_grd_1_a_date_with_the_month_written_out_is_read(text: str, expected: tuple[Day]) -> None:
    assert read(text) == [(text, expected)]


def test_grd_1_dia_before_a_full_date_keeps_the_full_date() -> None:
    assert read("dia 20 de dezembro") == [("20 de dezembro", day(2026, 12, 20))]
    assert read("dia 05/01") == [("05/01", day(2027, 1, 5))]


def test_grd_1_a_unit_after_the_number_wins_over_dia_before_it() -> None:
    [(text, _)] = read("todo dia 24 horas")

    assert text == "24 horas"


def test_grd_1_today_is_always_the_argument_never_the_system_clock() -> None:
    new_year_eve = datetime.date(2027, 12, 31)

    [tomorrow] = extract("amanhã", today=new_year_eve)

    assert tomorrow.candidates == (Day(datetime.date(2028, 1, 1)),)
