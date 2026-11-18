"""Prints recall and precision of retrieval on the labelled questions.

    uv run python scripts/retrieval_rates.py                       # the offline embedder
    uv run python scripts/retrieval_rates.py --model text-embedding-3-small

With a model, the questions and the knowledge base are embedded by the deployment named,
with the endpoint and key in `.env`. It costs a fraction of a cent.
"""

import argparse
import asyncio
import json
from pathlib import Path

from sandbox import sandbox

from frontdesk.evals.retrieval import load, measure
from frontdesk.providers.embeddings import Embedder, HashingEmbedder
from frontdesk.wiring import azure_openai_embedder, model_access_from_env

REPO = Path(__file__).resolve().parents[2]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", help="embedding deployment; the offline embedder when omitted")
    parser.add_argument("--max-distance", type=float, help="override the embedder's threshold")
    arguments = parser.parse_args()

    embedder: Embedder = HashingEmbedder()
    if arguments.model:
        endpoint, key = model_access_from_env(REPO / ".env")
        embedder = azure_openai_embedder(endpoint, key, arguments.model)
    if arguments.max_distance is not None:
        embedder.max_distance = arguments.max_distance

    queries = load(REPO / "evals" / "retrieval" / "queries.json")
    async with sandbox(embedder) as box:
        rates = await measure(box.sessions, embedder, queries)
    print(
        json.dumps(
            {
                "embedder": embedder.model,
                "max_distance": embedder.max_distance,
                "answerable_questions": rates.answerable,
                "recall_at_1": round(rates.recall_at_1, 3),
                "recall_at_3": round(rates.recall_at_k, 3),
                "precision_at_3": round(rates.precision_at_k, 3),
                "missed": rates.missed,
                "questions_with_no_answer_in_the_base": rates.unanswerable,
                "nothing_retrieved_for_them": round(rates.quiet_rate, 3),
                "something_retrieved_for": rates.noisy,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
