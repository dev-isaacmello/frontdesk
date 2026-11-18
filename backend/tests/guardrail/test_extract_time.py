"""GRD-1: every time of day in a reply is extracted, with both readings when it is ambiguous."""

import pytest

from frontdesk.guardrail import Count, Duration, Fact, TimeOfDay
from tests.guardrail.support import read


@pytest.mark.parametrize(
    ("text", "hour", "minute"),
    [
        ("14:30", 14, 30),
        ("09:05", 9, 5),
        ("0:00", 0, 0),
        ("14:30h", 14, 30),
    ],
)
def test_grd_1_time_with_a_colon_is_only_a_time(text: str, hour: int, minute: int) -> None:
    assert read(text) == [(text, (TimeOfDay(hour, minute),))]


@pytest.mark.parametrize(
    ("text", "candidates"),
    [
        ("14h", (Duration(840), TimeOfDay(14, 0))),
        ("14 h", (Duration(840), TimeOfDay(14, 0))),
        ("14hs", (Duration(840), TimeOfDay(14, 0))),
        ("14h30", (Duration(870), TimeOfDay(14, 30))),
        ("14h30min", (Duration(870), TimeOfDay(14, 30))),
        ("2 horas", (Duration(120), TimeOfDay(2, 0))),
    ],
)
def test_grd_1_hours_without_context_are_a_time_or_a_duration(
    text: str, candidates: tuple[Fact, ...]
) -> None:
    assert read(text) == [(text, candidates)]


@pytest.mark.parametrize(
    ("text", "value", "time"),
    [
        ("às 14 horas", "14 horas", TimeOfDay(14, 0)),
        ("às 2 horas", "2 horas", TimeOfDay(2, 0)),
        ("às 10h", "10h", TimeOfDay(10, 0)),
        ("Às 11h30", "11h30", TimeOfDay(11, 30)),
        ("às 9", "9", TimeOfDay(9, 0)),
        ("às dez e quinze", "dez e quinze", TimeOfDay(10, 15)),
        ("às 10 e 30", "10 e 30", TimeOfDay(10, 30)),
        ("às vinte e duas e trinta", "vinte e duas e trinta", TimeOfDay(22, 30)),
    ],
)
def test_grd_1_the_preposition_as_with_accent_makes_it_only_a_time(
    text: str, value: str, time: TimeOfDay
) -> None:
    assert read(text) == [(value, (time,))]


def test_grd_1_an_hour_without_period_is_never_read_as_afternoon() -> None:
    assert read("às 2") == [("2", (TimeOfDay(2, 0),))]


@pytest.mark.parametrize(
    ("text", "hour", "minute"),
    [
        ("9 da manhã", 9, 0),
        ("2 da tarde", 14, 0),
        ("8 da noite", 20, 0),
        ("7 da tarde", 19, 0),
        ("12 da noite", 0, 0),
        ("3 da madrugada", 3, 0),
        ("duas e meia da tarde", 14, 30),
        ("dez e quinze da manha", 10, 15),
        ("8h30 da noite", 20, 30),
        ("8 horas da noite", 20, 0),
        ("8:30 da noite", 20, 30),
        ("uma da tarde", 13, 0),
    ],
)
def test_grd_1_a_period_of_the_day_sets_the_clock_hour(text: str, hour: int, minute: int) -> None:
    assert read(text) == [(text, (TimeOfDay(hour, minute),))]


@pytest.mark.parametrize(
    ("text", "hour", "minute"),
    [
        ("meio-dia", 12, 0),
        ("meia-noite", 0, 0),
        ("Meio dia", 12, 0),
        ("meio-dia e meia", 12, 30),
    ],
)
def test_grd_1_noon_and_midnight_are_read(text: str, hour: int, minute: int) -> None:
    assert read(text) == [(text, (TimeOfDay(hour, minute),))]


def test_grd_1_a_number_and_a_half_is_a_time() -> None:
    assert read("2 e meia") == [("2 e meia", (TimeOfDay(2, 30),))]
    assert read("uma e meia") == [("uma e meia", (TimeOfDay(1, 30),))]


def test_grd_1_two_numbers_joined_by_e_without_context_are_two_counts() -> None:
    assert read("dez e quinze") == [("dez", (Count(10),)), ("quinze", (Count(15),))]


def test_grd_1_as_without_accent_is_a_time_or_a_count() -> None:
    assert read("as 9") == [("9", (TimeOfDay(9, 0), Count(9)))]
    assert read("das 9 às 18") == [
        ("9", (TimeOfDay(9, 0), Count(9))),
        ("18", (TimeOfDay(18, 0),)),
    ]


def test_grd_1_a_with_grave_accent_is_a_time_or_the_end_of_a_range() -> None:
    assert read("à 1 hora") == [("1 hora", (Duration(60), TimeOfDay(1, 0)))]
    assert read("de 2 à 5 pessoas") == [("2", (Count(2),)), ("5", (TimeOfDay(5, 0), Count(5)))]


def test_grd_1_a_number_after_as_that_is_no_clock_hour_is_a_count() -> None:
    assert read("às 25") == [("25", (Count(25),))]


def test_grd_1_a_range_of_opening_hours_yields_each_time() -> None:
    assert read("Abrimos das 9h às 19h.") == [
        ("9h", (Duration(540), TimeOfDay(9, 0))),
        ("19h", (TimeOfDay(19, 0),)),
    ]
