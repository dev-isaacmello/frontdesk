"""Loads the versioned catalog of models that ships with the package: prices and traits."""

import tomllib
from decimal import Decimal
from importlib import resources
from typing import Any

from frontdesk.providers.ledger import ModelPrice, PriceTable


def _catalog() -> dict[str, Any]:
    with resources.files("frontdesk.providers").joinpath("prices.toml").open("rb") as file:
        return tomllib.load(file)


def reasoning_models() -> frozenset[str]:
    """The models that accept a reasoning effort. The others reject a request that has one."""
    return frozenset(
        model for model, fields in _catalog()["models"].items() if fields.get("reasoning", True)
    )


def load_price_table() -> PriceTable:
    document = _catalog()
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
