"""Puts the running stack under load and reports throughput and latency (OPS-1).

Runs against a stack that is already up (`docker compose up`). A level is a number of
customers at once. Each of them, for the length of the level, opens a new web chat
conversation, asks a price, waits for the reply and starts over, so the offered load
follows what the system can answer and nothing piles up outside it. The customers
alternate between the two tenants of the seed.

    uv run python scripts/load.py --levels 1,6,12,24 --seconds 60 --out ../ops/load/offline.json

The latency is what the customer sees: from the start of the POST to the reply on the
event stream, over the customers who were answered. One who was told that a person is
taking over, which is what a turn that failed five times ends in, is counted apart.

With `--prometheus` the report also carries where the time went inside, per node of the
graph and in the queue, from the metrics the stack pushed (ADR 0015). With
`--sample-locks` it counts, once a second, the PostgreSQL sessions waiting for a lock,
which is how I look at the one row every model call updates (ADR 0013).
"""

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import time
from datetime import UTC, datetime
from itertools import cycle
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from frontdesk.agent.prompts import HANDOFF_NOTICE
from frontdesk.channels.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign

DEFAULT_SECRET = "local-webchat-secret-change-me"  # noqa: S105  the compose default, not a secret
QUESTIONS = {"navalha": "quanto custa o corte?", "ponto-final": "quanto custa a quadra?"}
STACK = Path(__file__).resolve().parents[2]
LOCKS = "select count(*) from pg_stat_activity where wait_event_type = 'Lock' \\watch 1\n"


def signed(secret: str, method: str, path: str, body: bytes = b"") -> dict[str, str]:
    timestamp, signature = sign(secret, datetime.now(UTC), method, path, body)
    return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature}


async def one_message(
    client: httpx.AsyncClient, secret: str, tenant: str, patience: float
) -> tuple[str | None, float]:
    """Asks one question in a new conversation. What came back, and after how many seconds."""
    session_id = uuid4().hex
    path = f"/channels/webchat/{tenant}/messages"
    body = json.dumps(
        {"session_id": session_id, "message_id": "1", "text": QUESTIONS[tenant]}
    ).encode()
    started = time.perf_counter()
    try:
        async with asyncio.timeout(patience):
            accepted = await client.post(
                path, content=body, headers=signed(secret, "POST", path, body)
            )
            accepted.raise_for_status()
            events = (
                f"/channels/webchat/{tenant}/conversations/{accepted.json()['conversation_id']}"
                f"/events?session_id={session_id}"
            )
            async with client.stream("GET", events, headers=signed(secret, "GET", events)) as feed:
                feed.raise_for_status()
                is_message = False
                async for line in feed.aiter_lines():
                    if line.startswith("event: "):
                        is_message = line == "event: message"
                    elif line.startswith("data: ") and is_message:
                        text = json.loads(line.removeprefix("data: "))["text"]
                        return text, time.perf_counter() - started
    except (TimeoutError, httpx.HTTPError):
        pass
    return None, time.perf_counter() - started


async def level(
    base_url: str, secret: str, customers: int, seconds: float, patience: float
) -> dict[str, Any]:
    """Runs `customers` side by side for `seconds` and describes what they got."""
    answered: list[float] = []
    handed_over: list[float] = []
    unanswered = 0
    tenants = cycle(QUESTIONS)
    limits = httpx.Limits(max_connections=customers * 2 + 2)
    async with httpx.AsyncClient(base_url=base_url, timeout=patience, limits=limits) as client:
        started = time.perf_counter()
        deadline = started + seconds

        async def customer() -> None:
            nonlocal unanswered
            while time.perf_counter() < deadline:
                text, took = await one_message(client, secret, next(tenants), patience)
                if text is None:
                    unanswered += 1
                elif text == HANDOFF_NOTICE:
                    # The agent gave up after its retries and a person was called: the
                    # customer was told, and was not answered.
                    handed_over.append(took)
                else:
                    answered.append(took)

        await asyncio.gather(*(customer() for _ in range(customers)))
        elapsed = time.perf_counter() - started
    return {
        "customers": customers,
        "seconds": round(elapsed, 1),
        "answered": len(answered),
        "handed_to_a_person": len(handed_over),
        "unanswered": unanswered,
        "replies_per_second": round(len(answered) / elapsed, 2),
        **_latency(answered),
    }


def _latency(seconds: list[float]) -> dict[str, int | None]:
    if len(seconds) < 2:
        only = round(seconds[0] * 1000) if seconds else None
        return {"p50_ms": only, "p95_ms": only, "max_ms": only}
    # Inclusive, so that a percentile is never above the slowest reply that was seen.
    cuts = statistics.quantiles(seconds, n=100, method="inclusive")
    return {
        "p50_ms": round(cuts[49] * 1000),
        "p95_ms": round(cuts[94] * 1000),
        "max_ms": round(max(seconds) * 1000),
    }


class LockWatch:
    """Counts, once a second, the database sessions that are waiting for a lock."""

    def __init__(self) -> None:
        self._psql = subprocess.Popen(
            ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-At"],  # noqa: S607
            cwd=STACK,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        assert self._psql.stdin is not None
        self._psql.stdin.write(LOCKS)
        self._psql.stdin.flush()

    def stop(self) -> dict[str, int]:
        self._psql.terminate()
        output, _ = self._psql.communicate()
        samples = [int(line) for line in output.split() if line.isdigit()]
        return {
            "samples": len(samples),
            "samples_with_a_waiter": sum(1 for waiting in samples if waiting),
            "most_waiting_at_once": max(samples, default=0),
        }


async def inside(prometheus: str, window_seconds: int) -> dict[str, Any]:
    """Where the time went, from the metrics: p95 per node, of a model call and of the queue."""
    window = f"{window_seconds}s"

    async def p95(metric: str, by: str | None) -> dict[str, int]:
        grouping = f"le, {by}" if by else "le"
        query = (
            f"histogram_quantile(0.95, sum by ({grouping}) (increase({metric}_bucket[{window}])))"
        )
        async with httpx.AsyncClient(base_url=prometheus, timeout=10) as client:
            response = await client.get("/api/v1/query", params={"query": query})
            response.raise_for_status()
        return {
            (series["metric"].get(by, "all") if by else "all"): round(
                float(series["value"][1]) * 1000
            )
            for series in response.json()["data"]["result"]
            if series["value"][1] != "NaN"
        }

    return {
        "node_p95_ms": await p95("frontdesk_node_duration_seconds", "frontdesk_node"),
        "model_call_p95_ms": await p95("frontdesk_model_duration_seconds", "frontdesk_node"),
        "queue_wait_p95_ms": await p95("frontdesk_queue_wait_seconds", None),
    }


async def run(arguments: argparse.Namespace) -> dict[str, Any]:
    secret = os.environ.get("FRONTDESK_WEBCHAT_SECRET", DEFAULT_SECRET)
    watch = LockWatch() if arguments.sample_locks else None
    started = time.time()
    levels = []
    for customers in arguments.levels:
        result = await level(
            arguments.base_url, secret, customers, arguments.seconds, arguments.patience
        )
        print(json.dumps(result), flush=True)
        levels.append(result)
        # What was in flight when the level ended is done; the next starts on an idle stack.
        await asyncio.sleep(3)
    report: dict[str, Any] = {"at": datetime.now(UTC).isoformat(timespec="seconds")}
    report["levels"] = levels
    if watch is not None:
        report["lock_waits"] = watch.stop()
    if arguments.prometheus:
        # The stack pushes every 15 seconds: the last points of the run are still on the way.
        await asyncio.sleep(20)
        report["inside"] = await inside(arguments.prometheus, round(time.time() - started) + 30)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8700")
    parser.add_argument(
        "--levels",
        type=lambda text: [int(part) for part in text.split(",")],
        default=[1, 6, 12, 24],
        help="customers at once, one level after the other",
    )
    parser.add_argument("--seconds", type=float, default=60, help="how long each level lasts")
    parser.add_argument("--patience", type=float, default=120, help="how long a reply may take")
    parser.add_argument("--prometheus", help="for example http://127.0.0.1:9790")
    parser.add_argument("--sample-locks", action="store_true")
    parser.add_argument("--out", type=Path, help="where to write the report as JSON")
    arguments = parser.parse_args()

    report = asyncio.run(run(arguments))
    text = json.dumps(report, indent=2) + "\n"
    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
