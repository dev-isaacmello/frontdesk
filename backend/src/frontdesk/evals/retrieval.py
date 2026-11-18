"""KB-2: recall and precision of retrieval on a labelled set of questions.

Each question names the one chunk of its tenant that answers it, or none: a question about
a price or a free slot is answered by a tool, and the right retrieval for it is nothing.
The questions go through the same search a turn uses, with the embedder's own threshold.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.knowledge import search
from frontdesk.providers.embeddings import Embedder
from frontdesk.seed import TENANTS


@dataclass(frozen=True)
class Query:
    tenant: str
    text: str
    expected: str | None


@dataclass(frozen=True)
class Rates:
    answerable: int
    found_first: int
    found_in_top: int
    retrieved_for_answerable: int
    unanswerable: int
    quiet: int
    """Unanswerable questions for which nothing was retrieved, as it should be."""
    missed: tuple[str, ...]
    noisy: tuple[str, ...]

    @property
    def recall_at_1(self) -> float:
        return self.found_first / self.answerable

    @property
    def recall_at_k(self) -> float:
        return self.found_in_top / self.answerable

    @property
    def precision_at_k(self) -> float:
        """Of the chunks shown to the planner for answerable questions, how many answer them."""
        return self.found_in_top / self.retrieved_for_answerable

    @property
    def quiet_rate(self) -> float:
        return self.quiet / self.unanswerable


def load(path: Path) -> list[Query]:
    return [
        Query(item["tenant"], item["query"], item["expected"])
        for item in json.loads(path.read_text())["queries"]
    ]


async def measure(
    sessions: SessionFactory, embedder: Embedder, queries: list[Query], *, limit: int = 3
) -> Rates:
    tenants = {tenant.slug: tenant for tenant in TENANTS}
    embedded = await embedder.embed([query.text for query in queries])
    first = top = retrieved = quiet = 0
    missed: list[str] = []
    noisy: list[str] = []
    for query, vector in zip(queries, embedded.vectors, strict=True):
        async with tenant_transaction(sessions, tenants[query.tenant].id) as session:
            chunks = await search(
                session, vector, embedder.model, max_distance=embedder.max_distance, limit=limit
            )
        titles = [chunk.title for chunk in chunks]
        if query.expected is None:
            quiet += not titles
            if titles:
                noisy.append(query.text)
            continue
        retrieved += len(titles)
        first += titles[:1] == [query.expected]
        top += query.expected in titles
        if query.expected not in titles:
            missed.append(query.text)
    answerable = sum(query.expected is not None for query in queries)
    return Rates(
        answerable=answerable,
        found_first=first,
        found_in_top=top,
        retrieved_for_answerable=retrieved,
        unanswerable=len(queries) - answerable,
        quiet=quiet,
        missed=tuple(missed),
        noisy=tuple(noisy),
    )
