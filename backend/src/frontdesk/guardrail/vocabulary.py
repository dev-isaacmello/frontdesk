"""The pt-BR words the guardrail gives meaning to, spelled lowercase and without accents."""

# Number words -------------------------------------------------------------------------------

UNITS: dict[str, int] = {
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
}
# "um" and "uma" are also the indefinite article, so alone they are not a number.
ARTICLES = frozenset({"um", "uma"})
TEENS: dict[str, int] = {
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "treze": 13,
    "quatorze": 14,
    "catorze": 14,
    "quinze": 15,
    "dezesseis": 16,
    "dezessete": 17,
    "dezoito": 18,
    "dezenove": 19,
}
TENS: dict[str, int] = {
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "sessenta": 60,
    "setenta": 70,
    "oitenta": 80,
    "noventa": 90,
}
HUNDREDS: dict[str, int] = {
    "cem": 100,
    "cento": 100,
    "duzentos": 200,
    "duzentas": 200,
    "trezentos": 300,
    "trezentas": 300,
    "quatrocentos": 400,
    "quatrocentas": 400,
    "quinhentos": 500,
    "quinhentas": 500,
    "seiscentos": 600,
    "seiscentas": 600,
    "setecentos": 700,
    "setecentas": 700,
    "oitocentos": 800,
    "oitocentas": 800,
    "novecentos": 900,
    "novecentas": 900,
}
THOUSAND = "mil"
AND = "e"
HALF = "meia"

# Words after a number that leave it without an exact value.
LARGE_MAGNITUDES = frozenset({"milhao", "milhoes", "bilhao", "bilhoes"})
VAGUE_AMOUNTS = frozenset({"pouco", "poucos", "poucas", "tanto", "tantos", "tantas", "tal", "pico"})
MASCULINE_HALF = "meio"
PERCENT_WORDS = ("por", "cento")

# Units ----------------------------------------------------------------------------------------

REAL_UNITS = frozenset({"real", "reais"})
CENT_UNITS = frozenset({"centavo", "centavos"})
HOUR_UNITS = frozenset({"h", "hs", "hr", "hrs", "hora", "horas"})
MINUTE_UNITS = frozenset({"min", "mins", "minuto", "minutos", "minutinho", "minutinhos"})
TIMES_SUFFIX = "x"
ORDINAL_MARKS = frozenset({"º", "°", "o"})
FIRST = "primeiro"

# Time of day ----------------------------------------------------------------------------------

NAMED_TIMES: dict[tuple[str, ...], int] = {
    ("meio-dia",): 12,
    ("meio", "dia"): 12,
    ("meia-noite",): 0,
    ("meia", "noite"): 0,
}
# Durations said without a number, in minutes.
FIXED_DURATIONS: dict[tuple[str, ...], int] = {
    ("meia", "hora"): 30,
    ("meia-hora",): 30,
    ("hora", "e", "meia"): 90,
}

# The hour said before each period of the day, mapped to the hour on a 24-hour clock.
PERIOD_CLOCK_HOURS: dict[str, dict[int, int]] = {
    "madrugada": {12: 0, **{hour: hour for hour in range(6)}},
    "manha": {hour: hour for hour in range(1, 12)},
    "tarde": {
        12: 12,
        **{hour: hour + 12 for hour in range(1, 8)},
        **{hour: hour for hour in range(13, 20)},
    },
    "noite": {
        12: 0,
        **{hour: hour + 12 for hour in range(6, 12)},
        **{hour: hour for hour in range(18, 24)},
    },
}
# Only "da": "2 de manhã" counts two things that happen in the morning.
PERIOD_LINK = "da"

# "às" with its accent can only introduce a time. Without the accent the same letters are also
# an article ("as 9 quadras"), and "à" is often written in ranges ("de 2 à 5 pessoas"), so those
# leave the time as one reading among others.
TIME_PREPOSITION = "as"
LOOSE_TIME_PREPOSITIONS = frozenset({"as", "das", "pelas"})
ACCENTED_LOOSE_TIME_PREPOSITION = "a"

# Duration -------------------------------------------------------------------------------------

DURATION_LEADS = frozenset(
    {
        "dura",
        "duram",
        "durar",
        "durou",
        "leva",
        "levam",
        "levar",
        "demora",
        "demoram",
        "demorar",
        "por",
        "durante",
    }
)
DURATION_TAIL = ("de", "duracao")

# Days -----------------------------------------------------------------------------------------

RELATIVE_DAYS: dict[str, int] = {"anteontem": -2, "ontem": -1, "hoje": 0, "amanha": 1}
DAY_AFTER_TOMORROW = ("depois", "de", "amanha")
TODAY = "hoje"
# What may stand between "hoje" and the weekday that names it: "hoje, sexta", "hoje é sexta".
TODAY_LINK_SYMBOLS = frozenset({",", "(", "-", ":"})
TODAY_LINK_VERB = "e"
DAY_OF_MONTH_LEADS = frozenset({"dia", "dias"})
MONTH_LINK = "de"

_WORKDAYS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4}
_WEEKEND = {"sabado": 5, "domingo": 6}
# Python's numbering: Monday is 0.
WEEKDAYS: dict[str, int] = {
    **{
        name + suffix: number
        for name, number in _WORKDAYS.items()
        for suffix in ("", "s", "-feira", "s-feiras")
    },
    **{name + suffix: number for name, number in _WEEKEND.items() for suffix in ("", "s")},
}
WEEKDAY_SUFFIX_WORDS = frozenset({"feira", "feiras"})

# The hyphenated words above; any other hyphen between letters separates two words.
COMPOUND_WORDS = frozenset(
    {"meio-dia", "meia-noite", "meia-hora"} | {name for name in WEEKDAYS if "-" in name}
)
NEXT_WEEK_LEADS = frozenset({"proxima", "proximo"})
NEXT_WEEK_TAILS: tuple[tuple[str, ...], ...] = (
    ("que", "vem"),
    ("da", "semana", "que", "vem"),
    ("da", "proxima", "semana"),
)

MONTHS: dict[str, int] = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
