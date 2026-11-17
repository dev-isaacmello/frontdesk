"""A deterministic stand-in for a language model.

It exists so that `docker compose up` gives a working conversation with no cloud account,
and so that load tests exercise the pipeline without paying for tokens. It understands a
handful of phrasings by keyword and follows a fixed script over the same tools a real
model would call. It is not a language model and nothing about answer quality should be
read from it.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from frontdesk.providers.port import ModelRequest, ModelResponse, ToolCall, Usage

_MODEL = "offline"
_HELP = "Olá! Posso informar preços, ver horários livres, agendar e cancelar. O que você precisa?"
_NO_BOOKINGS = "Você não tem agendamentos futuros."
_SLOTS_SHOWN = 6

_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cancel", ("cancel", "desmarc")),
    ("bookings", ("meus agendamentos", "meus horarios", "minhas reservas", "tenho marcado")),
    ("book", ("agendar", "agende", "marcar", "marque", "reservar", "reserve", "quero cortar")),
    ("availability", ("horario", "disponivel", "vaga", "livre", "tem hora")),
    ("prices", ("quanto", "preco", "valor", "custa", "servico", "tabela")),
)
_GREETINGS = ("oi", "ola", "bom dia", "boa tarde", "boa noite", "obrigad", "valeu")
_WEEKDAYS = ("segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo")
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")
_CLOCK = re.compile(r"\b(\d{1,2})\s*(?:h|:)\s*(\d{2})?|\bas\s+(\d{1,2})\b")
_TODAY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")

type Step = ToolCall | str


@dataclass(frozen=True)
class _Conversation:
    """What the script needs from a request: the last customer message and what came after."""

    said: str
    today: date
    results: dict[str, dict[str, Any]]
    calls_made: int

    @classmethod
    def read(cls, request: ModelRequest) -> "_Conversation":
        last_customer = max(
            index for index, message in enumerate(request.messages) if message.role == "user"
        )
        names: dict[str, str] = {}
        results: dict[str, dict[str, Any]] = {}
        for message in request.messages[last_customer + 1 :]:
            names.update({call.id: call.name for call in message.tool_calls})
            if message.role == "tool" and message.tool_call_id in names:
                results[names[message.tool_call_id]] = json.loads(message.content)
        today = _TODAY.search(request.system)
        assert today is not None, "the planner prompt always states the date"
        day, month, year = (int(part) for part in today.groups())
        return cls(
            said=_normalize(request.messages[last_customer].content),
            today=date(year, month, day),
            results=results,
            calls_made=len(names),
        )

    def call(self, tool: str, arguments: dict[str, Any]) -> ToolCall:
        return ToolCall(id=f"offline_{self.calls_made}", name=tool, arguments=arguments)


class OfflineProvider:
    name = "offline"

    async def complete(self, request: ModelRequest) -> ModelResponse:
        if request.output_schema is not None:
            customer_text = _normalize(request.messages[-1].content)
            return _response(
                request, json.dumps({"in_scope": _in_scope(customer_text), "wants_human": False})
            )
        return _response(request, _next_step(_Conversation.read(request)))


def _response(request: ModelRequest, step: Step) -> ModelResponse:
    text = step if isinstance(step, str) else None
    prompt = request.system + "".join(message.content for message in request.messages)
    return ModelResponse(
        text=text,
        tool_calls=() if isinstance(step, str) else (step,),
        stop_reason="end" if isinstance(step, str) else "tool_use",
        usage=Usage(input_tokens=len(prompt) // 4, output_tokens=max(1, len(text or "") // 4)),
        model=_MODEL,
        latency_ms=0,
    )


def _in_scope(said: str) -> bool:
    business = any(keyword in said for _, keywords in _INTENTS for keyword in keywords)
    greeting = any(said.startswith(greeting) for greeting in _GREETINGS)
    # Short answers such as "sim" or "pode ser" only make sense inside a conversation.
    return business or greeting or len(said.split()) <= 3


def _next_step(conversation: _Conversation) -> Step:
    match _intent(conversation.said):
        case "cancel":
            return _cancel(conversation)
        case "bookings":
            return _list_bookings(conversation)
        case "book":
            return _schedule(conversation, wants_booking=True)
        case "availability":
            return _schedule(conversation, wants_booking=False)
        case "prices":
            return _prices(conversation)
        case _:
            return _HELP


def _intent(said: str) -> str | None:
    for intent, keywords in _INTENTS:
        if any(keyword in said for keyword in keywords):
            return intent
    return None


def _prices(conversation: _Conversation) -> Step:
    catalog = conversation.results.get("list_services")
    if catalog is None:
        return conversation.call("list_services", {})
    asked = _match_service(conversation.said, catalog["services"])
    services = [asked] if asked else catalog["services"]
    return " ".join(_price_line(service) for service in services)


def _schedule(conversation: _Conversation, *, wants_booking: bool) -> Step:
    catalog = conversation.results.get("list_services")
    if catalog is None:
        return conversation.call("list_services", {})
    service = _match_service(conversation.said, catalog["services"])
    if service is None:
        names = ", ".join(each["name"] for each in catalog["services"])
        return f"Qual serviço você quer? Temos: {names}."
    day = _parse_day(conversation.said, conversation.today)
    if day is None:
        return f"Para qual dia você quer {service['name']}?"

    availability = conversation.results.get("check_availability")
    if availability is None:
        return conversation.call(
            "check_availability", {"service_id": service["id"], "date": day.isoformat()}
        )
    slots = _slots_line(service, day, availability)
    wanted = _parse_clock(conversation.said)
    if not wants_booking or wanted is None or slots is None:
        return slots or f"Não temos horários para {service['name']} em {day:%d/%m}."

    booking = conversation.results.get("create_booking")
    if booking is None:
        resource = _resource_free_at(availability, wanted, conversation.said)
        if resource is None:
            return f"Esse horário não está livre. {slots}"
        return conversation.call(
            "create_booking",
            {
                "service_id": service["id"],
                "resource_id": resource["resource_id"],
                "starts_at": f"{day.isoformat()}T{wanted}:00",
            },
        )
    if booking["status"] != "booked":
        return f"Não consegui agendar esse horário. {slots}"
    booked = booking["booking"]
    return f"Agendado: {_booking_line(booked)}, {_money(booked['price_cents'])}."


def _list_bookings(conversation: _Conversation) -> Step:
    listed = conversation.results.get("list_customer_bookings")
    if listed is None:
        return conversation.call("list_customer_bookings", {})
    if not listed["bookings"]:
        return _NO_BOOKINGS
    return "Seus agendamentos: " + "; ".join(map(_booking_line, listed["bookings"])) + "."


def _cancel(conversation: _Conversation) -> Step:
    listed = conversation.results.get("list_customer_bookings")
    if listed is None:
        return conversation.call("list_customer_bookings", {})
    if not listed["bookings"]:
        return _NO_BOOKINGS
    cancelled = conversation.results.get("cancel_booking")
    if cancelled is None:
        return conversation.call(
            "cancel_booking", {"booking_id": listed["bookings"][0]["booking_id"]}
        )
    if cancelled["status"] != "cancelled":
        return "Não consegui cancelar esse agendamento."
    return f"Cancelado: {_booking_line(cancelled['booking'])}."


def _match_service(said: str, services: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The service whose name appears in the message, preferring the most specific name."""

    def alias(service: dict[str, Any]) -> str:
        return _normalize(service["name"]).split("(")[0].strip()

    named = [service for service in services if alias(service) in said]
    return max(named, key=lambda service: len(alias(service)), default=None)


def _parse_day(said: str, today: date) -> date | None:
    if "depois de amanha" in said:
        return today + timedelta(days=2)
    if "amanha" in said:
        return today + timedelta(days=1)
    if "hoje" in said:
        return today
    written = _DATE.search(said)
    if written is not None:
        return date(today.year, int(written.group(2)), int(written.group(1)))
    for weekday, name in enumerate(_WEEKDAYS):
        if name in said:
            return today + timedelta(days=(weekday - today.weekday()) % 7)
    return None


def _parse_clock(said: str) -> str | None:
    found = _CLOCK.search(said)
    if found is None:
        return None
    hour = int(found.group(1) or found.group(3))
    return f"{hour:02d}:{found.group(2) or '00'}"


def _resource_free_at(availability: dict[str, Any], clock: str, said: str) -> dict[str, Any] | None:
    """A resource free at that time. A resource named by the customer is never swapped."""
    resources = availability["resources"]
    named = [each for each in resources if _normalize(each["resource_name"]) in said]
    for resource in named or resources:
        if clock in map(_clock_of, resource["starts_at"]):
            return dict(resource)
    return None


def _slots_line(service: dict[str, Any], day: date, availability: dict[str, Any]) -> str | None:
    offers = [
        f"{resource['resource_name']} às "
        + ", ".join(_clock_of(start) for start in resource["starts_at"][:_SLOTS_SHOWN])
        for resource in availability["resources"]
        if resource["starts_at"]
    ]
    if not offers:
        return None
    return f"Para {service['name']} em {day:%d/%m} tenho: {'; '.join(offers)}."


def _price_line(service: dict[str, Any]) -> str:
    base, *later = service["prices"]
    price = _money(base["price_cents"])
    for window in later:
        change = window["starts_at"][:5]
        price += f" até {change} e {_money(window['price_cents'])} a partir das {change}"
    return f"{service['name']}: {service['duration_minutes']} min, {price}."


def _booking_line(booking: dict[str, Any]) -> str:
    starts_at = booking["starts_at"]
    day = f"{starts_at[8:10]}/{starts_at[5:7]}"
    return (
        f"{booking['service_name']} com {booking['resource_name']}, {day} às {_clock_of(starts_at)}"
    )


def _clock_of(iso_datetime: str) -> str:
    return iso_datetime[11:16]


def _money(cents: int) -> str:
    reais = f"{cents // 100:,}".replace(",", ".")
    return f"R$ {reais},{cents % 100:02d}"


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))
