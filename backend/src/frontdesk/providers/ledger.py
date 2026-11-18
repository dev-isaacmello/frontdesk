"""Every model call, with its tokens and what it cost (CST-1)."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import ModelCall, Turn
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.providers.port import ModelResponse, Usage


class UnknownModelPriceError(LookupError):
    """A call was made on a model the price table does not list."""


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens. A cache price that is not listed costs the input price."""

    input: Decimal
    output: Decimal
    cache_read: Decimal | None = None
    cache_write: Decimal | None = None

    def cost_microusd(self, usage: Usage) -> int:
        # One USD per million tokens is one micro-USD per token, so no scaling is needed.
        cost = (
            usage.input_tokens * self.input
            + usage.output_tokens * self.output
            + usage.cache_read_tokens * (self.cache_read or self.input)
            + usage.cache_write_tokens * (self.cache_write or self.input)
        )
        return int(cost.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass(frozen=True)
class PriceTable:
    version: str
    models: dict[str, ModelPrice]

    def cost_microusd(self, model: str, usage: Usage) -> int:
        try:
            return self.models[model].cost_microusd(usage)
        except KeyError:
            raise UnknownModelPriceError(model) from None


@dataclass(frozen=True)
class ModelCallCost:
    node: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_microusd: int
    price_table_version: str


class ModelLedger:
    def __init__(self, sessions: SessionFactory, prices: PriceTable) -> None:
        self._sessions = sessions
        self._prices = prices

    async def record(
        self,
        *,
        tenant_id: UUID,
        turn_id: UUID | None,
        node: str,
        provider: str,
        response: ModelResponse,
    ) -> None:
        """Writes the call in its own transaction, so it survives a turn that fails later."""
        usage = response.usage
        async with tenant_transaction(self._sessions, tenant_id) as session:
            session.add(
                ModelCall(
                    tenant_id=tenant_id,
                    turn_id=turn_id,
                    node=node,
                    provider=provider,
                    model=response.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    latency_ms=response.latency_ms,
                    cost_microusd=self._prices.cost_microusd(response.model, usage),
                    price_table_version=self._prices.version,
                )
            )


async def turn_costs(session: AsyncSession, conversation_id: UUID) -> list[ModelCallCost]:
    """The model calls of a conversation, in the order they were made."""
    calls = await session.scalars(
        select(ModelCall)
        .join(Turn, Turn.id == ModelCall.turn_id)
        .where(Turn.conversation_id == conversation_id)
        .order_by(ModelCall.id)
    )
    return [
        ModelCallCost(
            node=call.node,
            model=call.model,
            input_tokens=call.input_tokens,
            output_tokens=call.output_tokens,
            latency_ms=call.latency_ms,
            cost_microusd=call.cost_microusd,
            price_table_version=call.price_table_version,
        )
        for call in calls
    ]
