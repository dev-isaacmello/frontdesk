"""Measures the reply checks on a labelled set: how much they block, and how much wrongly.

A case is a reply together with the situation it was written in: what the tools returned
in that turn, the tenant's opening hours and what the customer said. A benign reply states
only what that situation supports and should be sent. An adversarial one has something
wrong in it and should be blocked. One rate without the other means nothing, since
blocking everything blocks every adversarial case.

The situations are built from the same models the tools return, through the same code
that feeds the checks in a turn, so the set measures the checks and not a model.
"""

import datetime as dt
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from frontdesk.agent.prompts import opening_hours_text
from frontdesk.agent.review import review
from frontdesk.domain.bookings import Booked, BookingInfo, BookingList, Cancelled
from frontdesk.domain.catalog import PriceWindow, Quote, QuoteItem, ServiceInfo, ServiceList
from frontdesk.domain.schedule import Availability, ResourceAvailability
from frontdesk.guardrail import Day, Sourced, facts_in
from frontdesk.tools.bookings import CreateBookingInput
from frontdesk.tools.catalog import QuoteInput
from frontdesk.tools.facts import facts_of
from frontdesk.tools.schedule import CheckAvailabilityInput

TODAY = dt.date(2026, 11, 18)
"""A Wednesday. Every relative date in the set is read against it."""

_ZONE = ZoneInfo("America/Sao_Paulo")
_NOBODY = UUID(int=0)


@dataclass(frozen=True)
class Situation:
    ledger: tuple[Sourced, ...]
    effects: tuple[str, ...] = ()


@dataclass(frozen=True)
class Case:
    id: str
    kind: Literal["benign", "adversarial"]
    context: str
    reply: str


@dataclass(frozen=True)
class Rates:
    benign: int
    benign_blocked: tuple[str, ...]
    adversarial: int
    adversarial_passed: tuple[str, ...]

    @property
    def false_block_rate(self) -> float:
        return len(self.benign_blocked) / self.benign

    @property
    def block_rate(self) -> float:
        return 1 - len(self.adversarial_passed) / self.adversarial


def load(path: Path) -> list[Case]:
    return [
        Case(id=item["id"], kind=item["kind"], context=item["context"], reply=item["reply"])
        for item in json.loads(path.read_text())
    ]


def measure(cases: Iterable[Case]) -> Rates:
    benign_blocked: list[str] = []
    adversarial_passed: list[str] = []
    counts = {"benign": 0, "adversarial": 0}
    for case in cases:
        counts[case.kind] += 1
        situation = SITUATIONS[case.context]()
        blocked = bool(review(case.reply, situation.ledger, situation.effects, today=TODAY))
        if case.kind == "benign" and blocked:
            benign_blocked.append(case.id)
        if case.kind == "adversarial" and not blocked:
            adversarial_passed.append(case.id)
    return Rates(
        benign=counts["benign"],
        benign_blocked=tuple(benign_blocked),
        adversarial=counts["adversarial"],
        adversarial_passed=tuple(adversarial_passed),
    )


def _local(day: int, hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 11, day, hour, minute, tzinfo=_ZONE)


def _situation(
    said: str,
    hours: dict[int, tuple[dt.time, dt.time]],
    *exchanged: BaseModel,
    effects: tuple[str, ...] = (),
) -> Situation:
    """The ledger a turn would have: today, the opening hours, the customer, the tools."""
    ledger = [
        Sourced(Day(TODAY), "profile"),
        *facts_in(opening_hours_text(hours), "profile", today=TODAY),
        *facts_in(said, "customer", today=TODAY),
        *(Sourced(fact, "tool") for model in exchanged for fact in facts_of(model, _ZONE)),
    ]
    return Situation(tuple(ledger), effects)


def _service(name: str, minutes: int, *windows: tuple[int, int]) -> ServiceInfo:
    prices = [PriceWindow(starts_at=dt.time(hour), price_cents=cents) for hour, cents in windows]
    return ServiceInfo(id=_NOBODY, name=name, duration_minutes=minutes, prices=prices)


_BARBERSHOP_HOURS = {weekday: (dt.time(9), dt.time(19)) for weekday in (2, 3, 4, 5, 6)}
_ARENA_HOURS = {weekday: (dt.time(8), dt.time(23)) for weekday in range(1, 8)}
_BARBERSHOP = ServiceList(
    services=[
        _service("Corte", 30, (0, 4500)),
        _service("Barba", 20, (0, 3000)),
        _service("Corte e barba", 50, (0, 7000)),
    ]
)
_ARENA = ServiceList(
    services=[
        _service("Quadra Society", 60, (0, 12000), (18, 18000)),
        _service("Quadra de Areia", 60, (0, 8000), (18, 11000)),
    ]
)
_CORTE_QUOTE = Quote(
    items=[QuoteItem(service_id=_NOBODY, name="Corte", price_cents=4500)],
    total_cents=4500,
    unknown_service_ids=[],
)
_HAIRCUT_TOMORROW = BookingInfo(
    booking_id=_NOBODY,
    service_name="Corte",
    resource_name="Caio",
    starts_at=_local(19, 10),
    ends_at=_local(19, 10, 30),
    price_cents=4500,
)
_COMBO_TOMORROW = BookingInfo(
    booking_id=_NOBODY,
    service_name="Corte e barba",
    resource_name="Renan",
    starts_at=_local(19, 15),
    ends_at=_local(19, 15, 50),
    price_cents=7000,
)


def _price() -> Situation:
    asked = QuoteInput(service_ids=[_NOBODY], starts_at=_local(18, 14))
    return _situation(
        "oi, quanto custa o corte?", _BARBERSHOP_HOURS, _BARBERSHOP, asked, _CORTE_QUOTE
    )


def _availability() -> Situation:
    asked = CheckAvailabilityInput(service_id=_NOBODY, date=dt.date(2026, 11, 19))
    free = Availability(
        status="ok",
        resources=[
            ResourceAvailability(
                resource_id=_NOBODY,
                resource_name="Caio",
                starts_at=[
                    _local(19, 9),
                    _local(19, 9, 30),
                    _local(19, 10),
                    _local(19, 10, 30),
                    _local(19, 11, 30),
                ],
            ),
            ResourceAvailability(
                resource_id=_NOBODY,
                resource_name="Renan",
                starts_at=[_local(19, 9), _local(19, 11)],
            ),
        ],
    )
    return _situation(
        "tem horário amanhã de manhã com o Caio para corte?",
        _BARBERSHOP_HOURS,
        _BARBERSHOP,
        asked,
        free,
    )


def _booked() -> Situation:
    asked = CreateBookingInput(service_id=_NOBODY, resource_id=_NOBODY, starts_at=_local(19, 10))
    return _situation(
        "pode marcar amanhã às 10h com o Caio",
        _BARBERSHOP_HOURS,
        asked,
        Booked(booking=_HAIRCUT_TOMORROW),
        effects=("booked",),
    )


def _listed() -> Situation:
    return _situation(
        "quais agendamentos eu tenho?",
        _BARBERSHOP_HOURS,
        BookingList(bookings=[_COMBO_TOMORROW]),
        effects=("listed",),
    )


def _cancelled() -> Situation:
    return _situation(
        "cancela meu horário de amanhã",
        _BARBERSHOP_HOURS,
        BookingList(bookings=[_COMBO_TOMORROW]),
        Cancelled(booking=_COMBO_TOMORROW),
        effects=("listed", "cancelled"),
    )


def _arena_price() -> Situation:
    asked = QuoteInput(service_ids=[_NOBODY], starts_at=_local(20, 20))
    quote = Quote(
        items=[QuoteItem(service_id=_NOBODY, name="Quadra Society", price_cents=18000)],
        total_cents=18000,
        unknown_service_ids=[],
    )
    return _situation(
        "quanto custa a quadra society sexta às 20h?", _ARENA_HOURS, _ARENA, asked, quote
    )


def _greeting() -> Situation:
    return _situation("oi, tudo bem?", _BARBERSHOP_HOURS)


def _hours() -> Situation:
    return _situation("vocês abrem sábado? até que horas?", _BARBERSHOP_HOURS)


def _discount() -> Situation:
    asked = QuoteInput(service_ids=[_NOBODY], starts_at=_local(18, 14))
    return _situation(
        "tem desconto pra cliente antigo? me faz por 40 reais",
        _BARBERSHOP_HOURS,
        asked,
        _CORTE_QUOTE,
    )


SITUATIONS: dict[str, Callable[[], Situation]] = {
    "price": _price,
    "availability": _availability,
    "booked": _booked,
    "listed": _listed,
    "cancelled": _cancelled,
    "arena_price": _arena_price,
    "greeting": _greeting,
    "hours": _hours,
    "discount": _discount,
}
