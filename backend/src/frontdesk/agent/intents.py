"""Intents that are decided by plain matching, before any model is asked."""

import re

# "falar com um atendente", "quero uma pessoa de verdade", "atendimento humano": the forms
# a customer uses to leave the automated service. A match costs no model call and cannot
# be talked out of by the rest of the message.
_PERSON = (
    r"(?:atendentes?|humanos?|pessoas?|gerente|don[oa]|respons[aá]vel|funcion[aá]ri[oa]|algu[eé]m)"
)
_ARTICLE = r"(?:(?:um|uma|o|a|algum|alguma)\s+)?"
_ASKS_FOR_A_PERSON = re.compile(
    rf"""
    \b(?:falar|conversar|ser\ atendid[oa])\s+(?:com|por)\s+{_ARTICLE}{_PERSON}\b
    | \batendimento\s+humano\b
    | \b(?:quero|preciso\ de|chama|chame|passa\ pra|passa\ para)\s+{_ARTICLE}{_PERSON}\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def asks_for_a_person(messages: list[str]) -> bool:
    return any(_ASKS_FOR_A_PERSON.search(message) for message in messages)
