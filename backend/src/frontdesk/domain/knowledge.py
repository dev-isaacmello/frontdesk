"""The knowledge base of a tenant, and finding in it what helps answer a message."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import KbChunk


@dataclass(frozen=True)
class Chunk:
    title: str
    body: str
    distance: float
    """Cosine distance to the query: 0 is the same direction, 1 is unrelated."""


async def put_chunk(
    session: AsyncSession,
    tenant_id: UUID,
    title: str,
    body: str,
    embedding: list[float],
    embedding_model: str,
) -> None:
    """Adds a chunk, or replaces the one of the same title with its new text and vector."""
    await session.execute(
        insert(KbChunk)
        .values(
            tenant_id=tenant_id,
            title=title,
            body=body,
            embedding=embedding,
            embedding_model=embedding_model,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "title"],
            set_={"body": body, "embedding": embedding, "embedding_model": embedding_model},
        )
    )


async def search(
    session: AsyncSession,
    query: list[float],
    embedding_model: str,
    *,
    max_distance: float,
    limit: int = 3,
) -> list[Chunk]:
    """The chunks of the session's tenant closest to the query, nearest first.

    Only chunks embedded with the same model are read: a distance between vectors of two
    models is noise. The scan is exact, over the rows row-level security lets through.
    """
    distance = KbChunk.embedding.cosine_distance(query)
    rows = await session.execute(
        select(KbChunk.title, KbChunk.body, distance.label("distance"))
        .where(KbChunk.embedding_model == embedding_model, distance <= max_distance)
        .order_by(distance)
        .limit(limit)
    )
    return [Chunk(title, body, float(far)) for title, body, far in rows]
