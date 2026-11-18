"""pt-BR renderings of guardrail facts for the property tests, written apart from the parser."""

import datetime
from dataclasses import dataclass

from hypothesis import strategies as st

from frontdesk.guardrail import Count, Day, Duration, Fact, Money, TimeOfDay

_BELOW_TWENTY = (
    "zero",
    "um",
    "dois",
    "três",
    "quatro",
    "cinco",
    "seis",
    "sete",
    "oito",
    "nove",
    "dez",
    "onze",
    "doze",
    "treze",
    "quatorze",
    "quinze",
    "dezesseis",
    "dezessete",
    "dezoito",
    "dezenove",
)
_TENS = ("vinte", "trinta", "quarenta", "cinquenta", "sessenta", "setenta", "oitenta", "noventa")
_HUNDREDS = (
    "cento",
    "duzentos",
    "trezentos",
    "quatrocentos",
    "quinhentos",
    "seiscentos",
    "setecentos",
    "oitocentos",
    "novecentos",
)
_MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)
_WEEKDAYS = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")
_LAST_WEEKDAY_WITH_FEIRA = 4


@dataclass(frozen=True)
class Phrase:
    fact: Fact
    text: str


def spell(number: int, *, feminine: bool = False) -> str:
    """Write a number from 1 to 9999 in words."""
    if number >= 1000:
        thousands, rest = divmod(number, 1000)
        head = "mil" if thousands == 1 else f"{spell(thousands)} mil"
        if rest == 0:
            return head
        joiner = " e " if rest < 100 or rest % 100 == 0 else " "
        return head + joiner + spell(rest, feminine=feminine)
    if number == 100:
        return "cem"
    if number > 100:
        hundreds, rest = divmod(number, 100)
        head = _HUNDREDS[hundreds - 1]
        return head if rest == 0 else f"{head} e {spell(rest, feminine=feminine)}"
    if number >= 20:
        tens, unit = divmod(number, 10)
        head = _TENS[tens - 2]
        return head if unit == 0 else f"{head} e {spell(unit, feminine=feminine)}"
    if feminine and number in (1, 2):
        return ("uma", "duas")[number - 1]
    return _BELOW_TWENTY[number]


def _unit(amount: int, singular: str, plural: str) -> str:
    return singular if amount == 1 else plural


def _dotted(number: int) -> str:
    return f"{number:,}".replace(",", ".")


# Money ---------------------------------------------------------------------------------------


def _sign_and_reais(reais: int) -> Phrase:
    return Phrase(Money(reais * 100), f"R$ {reais}")


def _sign_glued_with_cents(cents: int) -> Phrase:
    return Phrase(Money(cents), f"R${cents // 100},{cents % 100:02d}")


def _sign_with_thousands_and_cents(cents: int) -> Phrase:
    return Phrase(Money(cents), f"R$ {_dotted(cents // 100)},{cents % 100:02d}")


def _reais_in_digits(reais: int) -> Phrase:
    return Phrase(Money(reais * 100), f"{reais} {_unit(reais, 'real', 'reais')}")


def _reais_with_decimal_comma(cents: int) -> Phrase:
    return Phrase(Money(cents), f"{cents // 100},{cents % 100:02d} reais")


def _reais_in_words(reais: int) -> Phrase:
    return Phrase(Money(reais * 100), f"{spell(reais)} {_unit(reais, 'real', 'reais')}")


def _reais_and_centavos(reais: int, centavos: int) -> Phrase:
    text = (
        f"{reais} {_unit(reais, 'real', 'reais')} e "
        f"{centavos} {_unit(centavos, 'centavo', 'centavos')}"
    )
    return Phrase(Money(reais * 100 + centavos), text)


def _only_centavos(centavos: int) -> Phrase:
    return Phrase(Money(centavos), f"{centavos} {_unit(centavos, 'centavo', 'centavos')}")


def money_phrases() -> st.SearchStrategy[Phrase]:
    cents = st.integers(1, 999_999)
    reais = st.integers(1, 9_999)
    centavos = st.integers(1, 99)
    return st.one_of(
        st.builds(_sign_and_reais, reais),
        st.builds(_sign_glued_with_cents, cents),
        st.builds(_sign_with_thousands_and_cents, cents),
        st.builds(_reais_in_digits, reais),
        st.builds(_reais_with_decimal_comma, cents),
        st.builds(_reais_in_words, reais),
        st.builds(_reais_and_centavos, reais, centavos),
        st.builds(_only_centavos, centavos),
    )


# Time of day ---------------------------------------------------------------------------------


def _hour_with_h(hour: int) -> Phrase:
    return Phrase(TimeOfDay(hour, 0), f"{hour}h")


def _hour_and_minute_with_h(hour: int, minute: int) -> Phrase:
    return Phrase(TimeOfDay(hour, minute), f"{hour}h{minute:02d}")


def _hour_and_minute_with_h_and_min(hour: int, minute: int) -> Phrase:
    return Phrase(TimeOfDay(hour, minute), f"{hour}h{minute:02d}min")


def _clock_with_colon(hour: int, minute: int) -> Phrase:
    return Phrase(TimeOfDay(hour, minute), f"{hour}:{minute:02d}")


def _clock_with_colon_and_leading_zero(hour: int, minute: int) -> Phrase:
    return Phrase(TimeOfDay(hour, minute), f"{hour:02d}:{minute:02d}")


def _at_hours(hour: int) -> Phrase:
    return Phrase(TimeOfDay(hour, 0), f"às {hour} horas")


def _at_bare_hour(hour: int) -> Phrase:
    return Phrase(TimeOfDay(hour, 0), f"às {hour}")


def _in_the_morning(hour: int) -> Phrase:
    return Phrase(TimeOfDay(hour, 0), f"{hour} da manhã")


def _in_the_afternoon(said_hour: int) -> Phrase:
    return Phrase(TimeOfDay(said_hour + 12, 0), f"{said_hour} da tarde")


def _in_the_evening(said_hour: int) -> Phrase:
    return Phrase(TimeOfDay(said_hour + 12, 0), f"{said_hour} da noite")


def _half_past_in_the_afternoon(said_hour: int) -> Phrase:
    text = f"{spell(said_hour, feminine=True)} e meia da tarde"
    return Phrase(TimeOfDay(said_hour + 12, 30), text)


def _at_quarter_past_in_words(hour: int) -> Phrase:
    return Phrase(TimeOfDay(hour, 15), f"às {spell(hour, feminine=True)} e quinze")


def time_phrases() -> st.SearchStrategy[Phrase]:
    hour = st.integers(0, 23)
    minute = st.integers(0, 59)
    return st.one_of(
        st.builds(_hour_with_h, hour),
        st.builds(_hour_and_minute_with_h, hour, minute),
        st.builds(_hour_and_minute_with_h_and_min, hour, minute),
        st.builds(_clock_with_colon, hour, minute),
        st.builds(_clock_with_colon_and_leading_zero, hour, minute),
        st.builds(_at_hours, st.integers(2, 23)),
        st.builds(_at_bare_hour, st.integers(2, 23)),
        st.builds(_in_the_morning, st.integers(1, 11)),
        st.builds(_in_the_afternoon, st.integers(1, 6)),
        st.builds(_in_the_evening, st.integers(7, 11)),
        st.builds(_half_past_in_the_afternoon, st.integers(1, 6)),
        st.builds(_at_quarter_past_in_words, st.integers(2, 23)),
        st.just(Phrase(TimeOfDay(12, 0), "meio-dia")),
        st.just(Phrase(TimeOfDay(0, 0), "meia-noite")),
    )


# Day -----------------------------------------------------------------------------------------


def _weekday_name(date: datetime.date) -> Phrase:
    return Phrase(Day(date), _WEEKDAYS[date.weekday()])


def _weekday_name_with_feira(date: datetime.date) -> Phrase:
    name = _WEEKDAYS[date.weekday()]
    suffix = "-feira" if date.weekday() <= _LAST_WEEKDAY_WITH_FEIRA else ""
    return Phrase(Day(date), name + suffix)


def _day_of_month(date: datetime.date) -> Phrase:
    return Phrase(Day(date), f"dia {date.day}")


def _day_and_month(date: datetime.date) -> Phrase:
    return Phrase(Day(date), f"{date.day}/{date.month}")


def _day_and_month_with_leading_zeros(date: datetime.date) -> Phrase:
    return Phrase(Day(date), f"{date.day:02d}/{date.month:02d}")


def _day_month_and_year(date: datetime.date) -> Phrase:
    return Phrase(Day(date), f"{date.day:02d}/{date.month:02d}/{date.year}")


def _day_and_month_name(date: datetime.date) -> Phrase:
    return Phrase(Day(date), f"{date.day} de {_MONTHS[date.month - 1]}")


def _day_month_name_and_year(date: datetime.date) -> Phrase:
    return Phrase(Day(date), f"{date.day} de {_MONTHS[date.month - 1]} de {date.year}")


def _days_ahead(today: datetime.date, first: int, last: int) -> st.SearchStrategy[datetime.date]:
    return st.integers(first, last).map(lambda days: today + datetime.timedelta(days=days))


def day_phrases(today: datetime.date) -> st.SearchStrategy[Phrase]:
    """Each form is drawn only from the dates it denotes when read on `today`."""
    within_a_week = _days_ahead(today, 1, 7)
    within_a_month = _days_ahead(today, 0, 27)
    within_a_year = _days_ahead(today, 0, 364)
    any_date = st.dates(datetime.date(2000, 1, 1), datetime.date(2099, 12, 31))
    return st.one_of(
        st.just(Phrase(Day(today), "hoje")),
        st.just(Phrase(Day(today + datetime.timedelta(days=1)), "amanhã")),
        st.just(Phrase(Day(today + datetime.timedelta(days=2)), "depois de amanhã")),
        st.builds(_weekday_name, within_a_week),
        st.builds(_weekday_name_with_feira, within_a_week),
        st.builds(_day_of_month, within_a_month),
        st.builds(_day_and_month, within_a_year),
        st.builds(_day_and_month_with_leading_zeros, within_a_year),
        st.builds(_day_month_and_year, any_date),
        st.builds(_day_and_month_name, within_a_year),
        st.builds(_day_month_name_and_year, any_date),
    )


# Duration ------------------------------------------------------------------------------------


def _minutes_abbreviated(minutes: int) -> Phrase:
    return Phrase(Duration(minutes), f"{minutes} min")


def _minutes_in_digits(minutes: int) -> Phrase:
    return Phrase(Duration(minutes), f"{minutes} {_unit(minutes, 'minuto', 'minutos')}")


def _minutes_in_words(minutes: int) -> Phrase:
    return Phrase(Duration(minutes), f"{spell(minutes)} {_unit(minutes, 'minuto', 'minutos')}")


def _hours_in_digits(hours: int) -> Phrase:
    return Phrase(Duration(hours * 60), f"{hours} {_unit(hours, 'hora', 'horas')}")


def _hours_in_words(hours: int) -> Phrase:
    text = f"{spell(hours, feminine=True)} {_unit(hours, 'hora', 'horas')}"
    return Phrase(Duration(hours * 60), text)


def _hours_and_a_half(hours: int) -> Phrase:
    text = f"{spell(hours, feminine=True)} {_unit(hours, 'hora', 'horas')} e meia"
    return Phrase(Duration(hours * 60 + 30), text)


def _hours_and_minutes(hours: int, minutes: int) -> Phrase:
    text = (
        f"{hours} {_unit(hours, 'hora', 'horas')} e {minutes} {_unit(minutes, 'minuto', 'minutos')}"
    )
    return Phrase(Duration(hours * 60 + minutes), text)


def _compact_with_the_word_duration(hours: int, minutes: int) -> Phrase:
    return Phrase(Duration(hours * 60 + minutes), f"{hours}h{minutes:02d} de duração")


def duration_phrases() -> st.SearchStrategy[Phrase]:
    hours = st.integers(1, 12)
    return st.one_of(
        st.builds(_minutes_abbreviated, st.integers(1, 600)),
        st.builds(_minutes_in_digits, st.integers(1, 600)),
        st.builds(_minutes_in_words, st.integers(1, 600)),
        st.just(Phrase(Duration(30), "meia hora")),
        st.builds(_hours_in_digits, hours),
        st.builds(_hours_in_words, hours),
        st.builds(_hours_and_a_half, hours),
        st.builds(_hours_and_minutes, hours, st.integers(1, 59)),
        st.builds(_compact_with_the_word_duration, hours, st.integers(0, 59)),
    )


# Count ---------------------------------------------------------------------------------------


def _count_in_digits(value: int) -> Phrase:
    return Phrase(Count(value), str(value))


def _count_in_words(value: int) -> Phrase:
    return Phrase(Count(value), spell(value))


def count_phrases() -> st.SearchStrategy[Phrase]:
    return st.one_of(
        st.builds(_count_in_digits, st.integers(0, 99_999)),
        st.builds(_count_in_words, st.integers(2, 9_999)),
    )


def phrases(today: datetime.date) -> st.SearchStrategy[Phrase]:
    return st.one_of(
        money_phrases(),
        time_phrases(),
        day_phrases(today),
        duration_phrases(),
        count_phrases(),
    )


def phrases_of_the_same_type(fact: Fact, today: datetime.date) -> st.SearchStrategy[Phrase]:
    if isinstance(fact, Money):
        return money_phrases()
    if isinstance(fact, TimeOfDay):
        return time_phrases()
    if isinstance(fact, Day):
        return day_phrases(today)
    if isinstance(fact, Duration):
        return duration_phrases()
    return count_phrases()
