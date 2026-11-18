"""POL-1 and GRD-6: what a reply may not say, whatever the model was told."""

import pytest

from frontdesk.policy.claims import claimed_actions, unbacked_claims
from frontdesk.policy.output import discount_offers


@pytest.mark.parametrize(
    "reply",
    [
        "Posso fazer com desconto pra você.",
        "Hoje tem promoção: corte e barba juntos saem mais barato.",
        "A primeira barba é grátis.",
        "Fica de graça se você trouxer um amigo.",
        "Te dou um cupom para a próxima visita.",
        "A barba sai como cortesia da casa.",
    ],
)
def test_pol_1_an_offer_of_a_discount_is_found(reply: str) -> None:
    assert discount_offers(reply) != []


@pytest.mark.parametrize(
    "reply",
    [
        "Não temos desconto, o corte custa R$ 45,00.",
        "Infelizmente não posso dar desconto.",
        "No momento não há nenhuma promoção.",
        "O corte custa R$ 45,00. Quer agendar?",
        "Sem desconto, o valor é R$ 45,00.",
    ],
)
def test_pol_1_declining_a_discount_is_not_an_offer(reply: str) -> None:
    assert discount_offers(reply) == []


@pytest.mark.parametrize(
    ("reply", "claims"),
    [
        ("Pronto, agendei seu corte com o Caio.", {"booked"}),
        ("Seu horário está marcado para amanhã.", {"booked"}),
        ("Reserva confirmada! Te vejo lá.", {"booked"}),
        ("Cancelei o seu agendamento.", {"cancelled"}),
        ("Seu horário foi desmarcado.", {"cancelled"}),
        ("Remarquei para as 16h.", {"rescheduled"}),
        ("Alterei seu horário para quinta.", {"rescheduled"}),
        ("Quer que eu agende para você?", set()),
        ("Posso cancelar, se preferir.", set()),
        ("Ainda não agendei nada. Qual horário você prefere?", set()),
        ("Não consegui agendar: esse horário não está livre.", set()),
        ("Você não tem nenhum horário marcado.", set()),
    ],
)
def test_grd_6_a_claim_of_an_action_is_read_from_the_reply(reply: str, claims: set[str]) -> None:
    assert claimed_actions(reply) == claims


def test_grd_6_a_claim_needs_a_tool_that_did_it() -> None:
    assert unbacked_claims("Pronto, agendei seu corte.", effects=[]) == {"booked"}
    assert unbacked_claims("Pronto, agendei seu corte.", effects=["booked"]) == set()
    assert unbacked_claims("Cancelei o seu agendamento.", effects=["booked"]) == {"cancelled"}
    assert unbacked_claims("Remarquei para as 16h.", effects=["rescheduled"]) == set()


def test_grd_6_a_booking_the_tools_listed_can_be_called_booked() -> None:
    assert unbacked_claims("Você tem um corte agendado para amanhã.", effects=["listed"]) == set()
