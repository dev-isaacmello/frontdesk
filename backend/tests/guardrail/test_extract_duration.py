"""GRD-1: every duration in a reply is extracted as minutes."""

import pytest

from frontdesk.guardrail import Duration, Fact, TimeOfDay
from tests.guardrail.support import read


@pytest.mark.parametrize(
    ("text", "minutes"),
    [
        ("30 min", 30),
        ("30min", 30),
        ("30 minutos", 30),
        ("1 minuto", 1),
        ("um minuto", 1),
        ("quarenta e cinco minutos", 45),
        ("15 minutinhos", 15),
        ("meia hora", 30),
        ("meia-hora", 30),
        ("hora e meia", 90),
    ],
)
def test_grd_1_minutes_are_only_a_duration(text: str, minutes: int) -> None:
    assert read(text) == [(text, (Duration(minutes),))]


@pytest.mark.parametrize(
    ("text", "candidates"),
    [
        ("uma hora", (Duration(60), TimeOfDay(1, 0))),
        ("1 hora", (Duration(60), TimeOfDay(1, 0))),
        ("duas horas", (Duration(120), TimeOfDay(2, 0))),
        ("uma hora e meia", (Duration(90), TimeOfDay(1, 30))),
        ("1 hora e 30 minutos", (Duration(90), TimeOfDay(1, 30))),
        ("1h e 30min", (Duration(90), TimeOfDay(1, 30))),
        ("1h30", (Duration(90), TimeOfDay(1, 30))),
    ],
)
def test_grd_1_hours_without_context_are_a_duration_or_a_time(
    text: str, candidates: tuple[Fact, ...]
) -> None:
    assert read(text) == [(text, candidates)]


@pytest.mark.parametrize(
    ("text", "value", "minutes"),
    [
        ("dura 2 horas", "2 horas", 120),
        ("por 2 horas", "2 horas", 120),
        ("durante duas horas", "duas horas", 120),
        ("leva 1h", "1h", 60),
        ("demora uma hora e meia", "uma hora e meia", 90),
        ("2 horas de duração", "2 horas", 120),
        ("1h30 de duração", "1h30", 90),
        ("1h30 de duracao", "1h30", 90),
    ],
)
def test_grd_1_a_duration_word_around_hours_makes_it_only_a_duration(
    text: str, value: str, minutes: int
) -> None:
    assert read(text) == [(value, (Duration(minutes),))]


def test_grd_1_hours_beyond_the_clock_are_only_a_duration() -> None:
    assert read("30 horas") == [("30 horas", (Duration(1800),))]


def test_grd_1_minutes_after_hours_need_their_unit_to_join_the_duration() -> None:
    [first, second] = read("2 horas e 3 cortes")

    assert first == ("2 horas", (Duration(120), TimeOfDay(2, 0)))
    assert second[0] == "3"
