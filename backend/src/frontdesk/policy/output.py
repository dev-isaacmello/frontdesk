"""POL-1: a reply never offers a discount, because none is registered anywhere."""

import re

from frontdesk.policy.sentences import affirmed

# The catalog has prices and no discounts, so any offer of one is invented, whether the
# owner's rules or the customer asked for it.
_DISCOUNT = re.compile(
    r"""
    \b(?:
        descontos? | promo[çc][ãa]o | promo[çc][õo]es | gr[áa]tis | gratuit[oa]s?
        | de\ gra[çc]a | cortesia | brindes? | cupo[mn]s? | abatimento | por\ conta\ da\ casa
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def discount_offers(reply: str) -> list[str]:
    """The words of the reply that offer a discount or something for free."""
    return [match.group(0) for match in affirmed(_DISCOUNT, reply)]
