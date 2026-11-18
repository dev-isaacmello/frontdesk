"""CST-1: what a model call costs, from the price table versioned in the repository."""

from decimal import Decimal

import pytest

from frontdesk.providers.ledger import ModelPrice, PriceTable, UnknownModelPriceError
from frontdesk.providers.port import Usage
from frontdesk.providers.prices import load_price_table, reasoning_models


def test_cst_1_cost_is_tokens_times_the_price_per_million() -> None:
    table = load_price_table()

    # One turn as estimated in the cost document: 10,700 input and 580 output tokens.
    # 10,700 x 0.25 + 580 x 2.00 = 2,675 + 1,160 micro-USD.
    cost = table.cost_microusd("gpt-5-mini", Usage(input_tokens=10_700, output_tokens=580))

    assert cost == 3_835


def test_cst_1_cached_input_is_priced_apart() -> None:
    table = load_price_table()

    # 200 x 0.25 + 1,000 x 0.025 + 90 x 2.00 = 50 + 25 + 180 micro-USD.
    cost = table.cost_microusd(
        "gpt-5-mini", Usage(input_tokens=200, cache_read_tokens=1_000, output_tokens=90)
    )

    assert cost == 255


def test_cst_1_a_fraction_of_a_micro_dollar_rounds_half_up() -> None:
    table = PriceTable(
        version="test", models={"m": ModelPrice(input=Decimal("0.25"), output=Decimal(0))}
    )

    assert table.cost_microusd("m", Usage(input_tokens=2, output_tokens=0)) == 1
    assert table.cost_microusd("m", Usage(input_tokens=1, output_tokens=0)) == 0


def test_cst_1_a_model_without_a_price_is_an_error_not_a_free_call() -> None:
    with pytest.raises(UnknownModelPriceError):
        load_price_table().cost_microusd("some-new-model", Usage(input_tokens=1, output_tokens=1))


def test_cst_1_the_table_says_when_and_where_each_price_was_read() -> None:
    table = load_price_table()

    assert table.version == "2026-11-17"
    assert table.models["offline"].cost_microusd(Usage(input_tokens=999, output_tokens=999)) == 0


def test_the_catalog_says_which_models_take_a_reasoning_effort() -> None:
    assert reasoning_models() == frozenset({"gpt-5-mini", "gpt-oss-120b"})


def test_cst_1_every_deployed_model_has_a_price() -> None:
    table = load_price_table()
    turn = Usage(input_tokens=1_000_000, output_tokens=1_000_000)

    assert table.cost_microusd("gpt-4.1-mini", turn) == 2_000_000
    assert table.cost_microusd("gpt-oss-120b", turn) == 750_000
