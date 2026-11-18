"""KB-2: the labelled questions, measured here with the offline embedder."""

from pathlib import Path

from frontdesk.db.session import SessionFactory
from frontdesk.evals.retrieval import load, measure
from frontdesk.providers.embeddings import HashingEmbedder

QUERIES = Path(__file__).resolve().parents[3] / "evals" / "retrieval" / "queries.json"


def test_kb_2_the_set_has_questions_with_an_answer_and_questions_without() -> None:
    queries = load(QUERIES)

    assert len(queries) == 30
    assert sum(query.expected is None for query in queries) == 6
    assert {query.tenant for query in queries} == {"navalha", "ponto-final"}


async def test_kb_2_recall_and_precision_of_the_offline_embedder(sessions: SessionFactory) -> None:
    """Matching by shared words: what the stack does with no model, as a floor."""
    rates = await measure(sessions, HashingEmbedder(), load(QUERIES))

    # 17 of the 24 answerable questions share a word with their chunk.
    assert (rates.answerable, rates.found_first, rates.found_in_top) == (24, 17, 17)
    assert round(rates.recall_at_k, 3) == 0.708
    assert round(rates.precision_at_k, 3) == 0.773
    assert "onde vocês ficam?" in rates.missed
    assert (rates.unanswerable, rates.quiet) == (6, 2)
