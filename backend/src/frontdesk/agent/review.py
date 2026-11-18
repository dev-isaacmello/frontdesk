"""The checks a draft reply has to pass before it is sent, as one list of problems.

Deterministic checks, none of them a model: that the draft is a text at all, the numeric
guardrail, the ban on discounts, and claimed actions against what the tools did. Each
problem is worded for the planner, which gets one chance to write the reply again.
"""

import datetime
from collections.abc import Iterable

from frontdesk.guardrail import Sourced, check
from frontdesk.policy.claims import Action, unbacked_claims
from frontdesk.policy.output import discount_offers
from frontdesk.policy.shape import not_a_text

_NOT_A_TEXT = {
    "empty": "a resposta veio vazia: escreva a resposta ao cliente",
    "garbled": (
        "a resposta não é um texto legível: escreva de novo, em português, "
        "com frases completas e sem símbolos soltos"
    ),
}

_CLAIM_WORDS: dict[Action, str] = {
    "booked": "agendado",
    "cancelled": "cancelado",
    "rescheduled": "alterado",
}


def review(
    reply: str,
    ledger: Iterable[Sourced],
    effects: Iterable[str],
    *,
    today: datetime.date,
    knowledge: str = "",
) -> list[str]:
    """What is wrong with the reply, in pt-BR, or an empty list when it may be sent.

    `knowledge` is what was retrieved from the tenant's knowledge base for this turn. A
    word such as "gratuito" that the owner wrote there may be repeated; anywhere else it
    is an offer nobody registered.
    """
    shape = not_a_text(reply)
    if shape is not None:
        # Nothing else is worth saying about a draft that is not a text.
        return [_NOT_A_TEXT[shape]]
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
    written_by_the_owner = knowledge.lower()
    problems.extend(
        f'"{word}": desconto, promoção ou gratuidade não existem'
        for word in discount_offers(reply)
        if word.lower() not in written_by_the_owner
    )
    problems.extend(
        # The word is quoted so that the planner knows what to take out of its next draft.
        f'"{word}": a resposta diz que algo foi {_CLAIM_WORDS[action]}, '
        "mas nenhuma ferramenta fez isso; tire essa ideia da frase, não troque só a palavra"
        for action, word in sorted(unbacked_claims(reply, effects).items())
    )
    return problems
