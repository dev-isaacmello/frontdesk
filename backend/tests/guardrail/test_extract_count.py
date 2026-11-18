"""GRD-1: every remaining integer in a reply is extracted as a count, and non-values are skipped."""

import datetime
import unicodedata

import pytest

from frontdesk.guardrail import Count, Day, Money, TimeOfDay, extract
from tests.guardrail.support import TODAY, read


@pytest.mark.parametrize(
    ("text", "value", "count"),
    [
        ("2 cortes", "2", 2),
        ("1 vaga", "1", 1),
        ("duas quadras", "duas", 2),
        ("Três barbeiros", "Três", 3),
        ("dezesseis", "dezesseis", 16),
        ("noventa e nove", "noventa e nove", 99),
        ("cem", "cem", 100),
        ("cento e cinco", "cento e cinco", 105),
        ("mil", "mil", 1000),
        ("dois mil e quinhentos", "dois mil e quinhentos", 2500),
        ("mil duzentos e cinquenta", "mil duzentos e cinquenta", 1250),
        ("1.200 pessoas", "1.200", 1200),
        ("3 mil pessoas", "3 mil", 3000),
        ("2x por semana", "2x", 2),
        ("2 de manhã", "2", 2),
    ],
)
def test_grd_1_a_remaining_integer_is_a_count(text: str, value: str, count: int) -> None:
    assert read(text) == [(value, (Count(count),))]


@pytest.mark.parametrize(
    "text",
    [
        "Tenho uma opção para você",
        "um corte e uma barba",
        "Só um momento",
        "Tenho uma de manhã e outra à tarde",
        "todo dia uma promoção",
    ],
)
def test_grd_1_um_and_uma_alone_are_articles_not_values(text: str) -> None:
    assert read(text) == []


def test_grd_1_um_inside_a_larger_number_counts() -> None:
    assert read("vinte e um") == [("vinte e um", (Count(21),))]
    assert read("mil e um") == [("mil e um", (Count(1001),))]


def test_grd_1_numbers_that_do_not_form_one_cardinal_stay_separate() -> None:
    assert read("dois e três") == [("dois", (Count(2),)), ("três", (Count(3),))]


@pytest.mark.parametrize(
    "text",
    [
        "1. Corte\n2) Barba",
        "Opções:\n  1. Corte\n  2. Barba",
        "*1.* Corte\n*2.* Barba",
    ],
)
def test_grd_1_list_markers_at_the_start_of_a_line_are_not_values(text: str) -> None:
    assert read(text) == []


def test_grd_1_values_after_a_list_marker_are_still_read() -> None:
    assert read("1. Corte: R$ 45\n2. Barba: R$ 30") == [
        ("R$ 45", (Money(4500),)),
        ("R$ 30", (Money(3000),)),
    ]


def test_grd_1_a_number_that_ends_a_sentence_on_its_own_line_is_a_value() -> None:
    assert read("As vagas são\n45.") == [("45", (Count(45),))]


def test_grd_1_a_line_opening_number_that_does_not_count_up_from_one_is_a_value() -> None:
    assert read("As vagas são\n45. Posso confirmar?") == [("45", (Count(45),))]
    assert read("1. Corte\n2. Barba\n45. Posso confirmar?") == [("45", (Count(45),))]


@pytest.mark.parametrize("text", ["H2O", "quadra A1", "sala B12 no bloco C3"])
def test_grd_1_digits_inside_a_word_or_code_are_not_values(text: str) -> None:
    assert read(text) == []


def test_grd_1_text_with_decomposed_accents_is_read_with_spans_of_the_original() -> None:
    tomorrow = "Amanha\N{COMBINING TILDE}"
    reply = tomorrow + " a\N{COMBINING GRAVE ACCENT}s 10h"
    assert reply == unicodedata.normalize("NFD", "Amanhã às 10h")

    found = extract(reply, today=TODAY)

    assert [(value.text, value.start, value.end) for value in found] == [
        (tomorrow, 0, 7),
        ("10h", 12, 15),
    ]
    assert [value.candidates for value in found] == [
        (Day(datetime.date(2026, 11, 18)),),
        (TimeOfDay(10, 0),),
    ]


def test_grd_1_digits_of_another_script_are_read_as_digits() -> None:
    fullwidth = "\N{FULLWIDTH DIGIT FOUR}\N{FULLWIDTH DIGIT FIVE}"

    assert read(fullwidth + " vagas") == [(fullwidth, (Count(45),))]


def test_grd_1_a_digit_run_too_long_to_be_a_quantity_does_not_break_the_reading() -> None:
    digits = "9" * 5000

    assert read(digits + " e 2 cortes") == [(digits, ()), ("2", (Count(2),))]
