"""The checks a draft reply has to pass before it is sent, as one list of problems.

Three deterministic checks, none of them a model: the numeric guardrail, the ban on
discounts, and claimed actions against what the tools did. Each problem is worded for the
planner, which gets one chance to write the reply again.
"""

import datetime
from collections.abc import Iterable

from frontdesk.guardrail import Sourced, check
from frontdesk.policy.claims import Action, unbacked_claims
from frontdesk.policy.output import discount_offers

_CLAIM_WORDS: dict[Action, str] = {
    "booked": "agendado",
    "cancelled": "cancelado",
    "rescheduled": "alterado",
}


def review(
    reply: str, ledger: Iterable[Sourced], effects: Iterable[str], *, today: datetime.date
) -> list[str]:
    """What is wrong with the reply, in pt-BR, or an empty list when it may be sent."""
    problems: list[str] = []
    for violation in check(reply, ledger, today=today).violations:
        if violation.reason == "untyped":
            problems.append(
                f'"{violation.text}" não pode ser dito: percentual, telefone ou valor aproximado'
            )
        else:
            problems.append(
                f'"{violation.text}" não veio de nenhuma ferramenta deste atendimento, '
                "nem do horário de funcionamento, nem da mensagem do cliente"
            )
    problems.extend(
        f'"{word}": desconto, promoção ou gratuidade não existem' for word in discount_offers(reply)
    )
    problems.extend(
        f"a resposta diz que algo foi {_CLAIM_WORDS[action]}, mas nenhuma ferramenta fez isso"
        for action in sorted(unbacked_claims(reply, effects))
    )
    return problems
