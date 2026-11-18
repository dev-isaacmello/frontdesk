"""GRD-7: before anything else, what goes to a customer has to be a text."""

import pytest

from frontdesk.policy.shape import not_a_text

# What `gpt-oss-120b` wrote to "ola" and "tudo bem?" in the first real WhatsApp
# conversation, as it was sent: every check passed, because it states no number, offers
# no discount and claims no action.
SENT_TO_A_CUSTOMER = (
    "Seu\xa0...\xa0​\xa0\xa0\xa0​\xa0\xa0\xa0\xa0...\xa0\xa0....\xa0...\n\n\n\n"
    "Sorry\xa0...\xa0?\xa0\n\n\n…\n\n​\xa0\n\n\n\n```\n\nOops\xa0…\xa0/\xa0?\xa0\n\n\n\n"
    "\xa0\xa0\n\n\n\n\n\n\n\n?…\xa0\n\n\n\n...\xa0\n\n\n\n\xa0—\n\n\xa0\n\n\n\n\n\n\n\n\xa0\n\n\n\n…"
    "\n\n\xa0\n\n\n\n\n\n\n\n…\xa0\n\n\n\n."
)


@pytest.mark.parametrize("draft", ["", "   ", "\n\n", "​\xa0\n"])
def test_grd_7_an_empty_draft_is_not_a_reply(draft: str) -> None:
    """The same conversation: an empty reply was closed as replied and refused by the channel."""
    assert not_a_text(draft) == "empty"


def test_grd_7_a_draft_that_is_mostly_symbols_is_not_a_reply() -> None:
    assert not_a_text(SENT_TO_A_CUSTOMER) == "garbled"
    assert not_a_text("... ? … / ```") == "garbled"


@pytest.mark.parametrize(
    "reply",
    [
        "O corte custa R$ 45,00.",
        "R$ 45,00.",
        "Sim!",
        "Oi! Como posso ajudar?",
        "Temos estes horários amanhã:\n- 09:00\n- 10:30\n- 14:00\n\nQual você prefere?",
        "Aceitamos Pix, além de cartão de débito e crédito.",
        "10h, 11h ou 14h?",
    ],
)
def test_grd_7_an_ordinary_reply_is_a_text(reply: str) -> None:
    assert not_a_text(reply) is None
