"""Measures latency from a message accepted by the API to its reply on the event stream.

Runs against a stack that is already up (`docker compose up`). Each message is a new web
chat session, so the conversations are independent and can be processed in parallel.

    uv run python scripts/latency.py --messages 200 --concurrency 10
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from frontdesk.channels.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign

DEFAULT_SECRET = "local-webchat-secret-change-me"  # noqa: S105  the compose default, not a secret
TENANT = "navalha"
QUESTION = "quanto custa o corte?"


def signed(secret: str, method: str, path: str, body: bytes = b"") -> dict[str, str]:
    timestamp, signature = sign(secret, datetime.now(UTC), method, path, body)
    return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature}


async def one_message(client: httpx.AsyncClient, secret: str) -> float:
    """Sends one message and returns the seconds until its reply arrived."""
    session_id = uuid4().hex
    path = f"/channels/webchat/{TENANT}/messages"
    body = json.dumps({"session_id": session_id, "message_id": "1", "text": QUESTION}).encode()

    started = time.perf_counter()
    accepted = await client.post(path, content=body, headers=signed(secret, "POST", path, body))
    accepted.raise_for_status()
    conversation_id = accepted.json()["conversation_id"]

    events = (
        f"/channels/webchat/{TENANT}/conversations/{conversation_id}/events?session_id={session_id}"
    )
    async with client.stream("GET", events, headers=signed(secret, "GET", events)) as stream:
        stream.raise_for_status()
        async for line in stream.aiter_lines():
            if line.startswith("event: message"):
                return time.perf_counter() - started
    raise RuntimeError("the stream closed before the reply")


async def measure(base_url: str, secret: str, messages: int, concurrency: int) -> list[float]:
    limit = asyncio.Semaphore(concurrency)
    limits = httpx.Limits(max_connections=concurrency * 2)
    async with httpx.AsyncClient(base_url=base_url, timeout=60, limits=limits) as client:

        async def bounded() -> float:
            async with limit:
                return await one_message(client, secret)

        return list(await asyncio.gather(*(bounded() for _ in range(messages))))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8700")
    parser.add_argument("--messages", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=10)
    arguments = parser.parse_args()
    secret = os.environ.get("FRONTDESK_WEBCHAT_SECRET", DEFAULT_SECRET)

    started = time.perf_counter()
    seconds = asyncio.run(
        measure(arguments.base_url, secret, arguments.messages, arguments.concurrency)
    )
    elapsed = time.perf_counter() - started

    cuts = statistics.quantiles(seconds, n=100)
    print(
        json.dumps(
            {
                "messages": len(seconds),
                "concurrency": arguments.concurrency,
                "p50_ms": round(cuts[49] * 1000),
                "p95_ms": round(cuts[94] * 1000),
                "max_ms": round(max(seconds) * 1000),
                "messages_per_second": round(len(seconds) / elapsed, 1),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
