"""Loads the versioned price table that ships with the package."""

import tomllib
from decimal import Decimal
from importlib import resources
from typing import Any

from frontdesk.providers.ledger import ModelPrice, PriceTable


def load_price_table() -> PriceTable:
    with resources.files("frontdesk.providers").joinpath("prices.toml").open("rb") as file:
        document = tomllib.load(file)
    return PriceTable(
        version=document["version"],
        models={model: _price(fields) for model, fields in document["models"].items()},
    )


def _price(fields: dict[str, Any]) -> ModelPrice:
    def optional(key: str) -> Decimal | None:
        return Decimal(fields[key]) if key in fields else None

    return ModelPrice(
        input=Decimal(fields["input"]),
        output=Decimal(fields["output"]),
        cache_read=optional("cache_read"),
        cache_write=optional("cache_write"),
    )
