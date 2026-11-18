"""Breaks the running stack on purpose and checks what the customers got (OPS-1).

Runs against the local stack (`docker compose up`), which it stops and restarts parts of.
Two scenarios, each ending with the stack as it found it:

    uv run python scripts/chaos.py worker-killed --out ../ops/chaos/worker-killed.json
    uv run python scripts/chaos.py model-down --out ../ops/chaos/model-down.json

`worker-killed` sends a burst of first messages, kills the worker with SIGKILL while they
are in flight, starts it again and waits. It passes when every customer got exactly one
reply and no message was left without a turn.

`model-down` restarts the worker pointed at an address where no model answers, sends a few
messages and waits. It passes when every customer was told a person is taking over,
exactly once, no model call was recorded, and after the worker is put back a new customer
is answered. This is the rehearsal of docs/runbooks/model-provider-down.md.

What the customers got is read from PostgreSQL as its superuser, through `docker compose
exec`, because the check is across tenants and the application's role cannot do that.
Run it with the environment the stack was started with: putting the worker back is a
`docker compose up` of it, which reads the same variables.
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
from uuid import UUID, uuid4

import httpx

from frontdesk.agent.prompts import HANDOFF_NOTICE
from frontdesk.channels.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign

DEFAULT_SECRET = "local-webchat-secret-change-me"  # noqa: S105  the compose default, not a secret
QUESTIONS = {"navalha": "quanto custa o corte?", "ponto-final": "quanto custa a quadra?"}
STACK = Path(__file__).resolve().parents[2]

# Where nothing listens: a model call is refused at once, like a provider that is down.
NOWHERE = {
    "FRONTDESK_MODEL_PROVIDER": "azure_openai",
    "FRONTDESK_MODEL": "gpt-oss-120b",
    "FRONTDESK_EMBEDDING_MODEL": "text-embedding-3-small",
    "FRONTDESK_AZURE_OPENAI_ENDPOINT": "http://127.0.0.1:9",
    "FRONTDESK_AZURE_OPENAI_API_KEY": "not-a-key",
}


def compose(
    *arguments: str, environment: dict[str, str] | None = None, stdin: str | None = None
) -> str:
    done = subprocess.run(  # noqa: S603  fixed commands of this script
        ["docker", "compose", *arguments],  # noqa: S607
        cwd=STACK,
        env={**os.environ, **(environment or {})},
        input=stdin,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def sql(query: str, conversations: list[str]) -> list[list[str]]:
    """Runs a query over the conversations of this run, which it names as `:'ids'`.

    The ids reach psql as a variable and not as text of the query.
    """
    ids = "{" + ",".join(str(UUID(conversation)) for conversation in conversations) + "}"
    rows = compose(
        "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", "frontdesk", "-At",
        "-v", f"ids={ids}",
        stdin=query + ";\n",
    )  # fmt: skip
    return [line.split("|") for line in rows.splitlines() if line]


def signed(secret: str, method: str, path: str, body: bytes = b"") -> dict[str, str]:
    timestamp, signature = sign(secret, datetime.now(UTC), method, path, body)
    return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature}


async def ask(
    client: httpx.AsyncClient, secret: str, tenant: str, patience: float, sent: list[str]
) -> tuple[str | None, float]:
    """One first message. What came back, if anything did, and after how many seconds."""
    session_id = uuid4().hex
    path = f"/channels/webchat/{tenant}/messages"
    body = json.dumps(
        {"session_id": session_id, "message_id": "1", "text": QUESTIONS[tenant]}
    ).encode()
    started = time.perf_counter()
    accepted = await client.post(path, content=body, headers=signed(secret, "POST", path, body))
    accepted.raise_for_status()
    conversation_id = accepted.json()["conversation_id"]
    sent.append(conversation_id)
    events = (
        f"/channels/webchat/{tenant}/conversations/{conversation_id}/events?session_id={session_id}"
    )
    is_message = False
    try:
        async with (
            asyncio.timeout(patience),
            client.stream("GET", events, headers=signed(secret, "GET", events)) as feed,
        ):
            feed.raise_for_status()
            async for line in feed.aiter_lines():
                if line.startswith("event: "):
                    is_message = line == "event: message"
                elif line.startswith("data: ") and is_message:
                    text = json.loads(line.removeprefix("data: "))["text"]
                    return text, time.perf_counter() - started
    except TimeoutError:
        pass
    return None, time.perf_counter() - started


def what_happened(conversations: list[str]) -> dict[str, Any]:
    """The state of the conversations of this run, as the database has it."""
    [[waiting]] = sql(
        "select count(*) from messages where direction = 'in' and turn_id is null "
        "and conversation_id = any(:'ids'::uuid[])",
        conversations,
    )
    replies = sql(
        "select said, count(*) from (select count(*) filter (where m.direction = 'out') as said "
        "from conversations c left join messages m on m.conversation_id = c.id "
        "where c.id = any(:'ids'::uuid[]) group by c.id) per_conversation "
        "group by said order by said",
        conversations,
    )
    turns = sql(
        "select status, coalesce(outcome, '-'), count(*) from turns "
        "where conversation_id = any(:'ids'::uuid[]) group by 1, 2 order by 1, 2",
        conversations,
    )
    handoffs = sql(
        "select reason, count(*) from handoffs "
        "where conversation_id = any(:'ids'::uuid[]) group by 1",
        conversations,
    )
    [[model_calls]] = sql(
        "select count(*) from model_calls where turn_id in "
        "(select id from turns where conversation_id = any(:'ids'::uuid[]))",
        conversations,
    )
    return {
        "conversations": len(conversations),
        "messages_without_a_turn": int(waiting),
        "conversations_by_replies_sent": {said: int(count) for said, count in replies},
        "turns": {f"{status}/{outcome}": int(count) for status, outcome, count in turns},
        "handoffs": {reason: int(count) for reason, count in handoffs},
        "model_calls": int(model_calls),
    }


def _seconds(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"fastest_s": None, "median_s": None, "slowest_s": None}
    return {
        "fastest_s": round(min(values), 1),
        "median_s": round(statistics.median(values), 1),
        "slowest_s": round(max(values), 1),
    }


async def worker_killed(arguments: argparse.Namespace, secret: str) -> dict[str, Any]:
    sent: list[str] = []
    tenants = cycle(QUESTIONS)
    timeout = httpx.Timeout(30, read=None)
    async with httpx.AsyncClient(base_url=arguments.base_url, timeout=timeout) as client:
        asking = [
            asyncio.create_task(ask(client, secret, next(tenants), arguments.patience, sent))
            for _ in range(arguments.customers)
        ]
        await asyncio.sleep(arguments.kill_after)
        await asyncio.to_thread(compose, "kill", "-s", "SIGKILL", "worker")
        killed = time.perf_counter()
        in_flight = sum(1 for task in asking if not task.done())
        await asyncio.sleep(arguments.down)
        await asyncio.to_thread(compose, "start", "worker")
        restarted = time.perf_counter()
        answers = await asyncio.gather(*asking)
        recovered = time.perf_counter()

    state = what_happened(sent)
    replied = [seconds for text, seconds in answers if text is not None]
    return {
        "scenario": "worker-killed",
        "customers": arguments.customers,
        "killed_after_s": arguments.kill_after,
        "unanswered_when_killed": in_flight,
        "worker_down_s": round(restarted - killed, 1),
        "last_reply_after_restart_s": round(recovered - restarted, 1),
        "answered": len(replied),
        "reply_time": _seconds(replied),
        "database": state,
        "passed": (
            len(replied) == arguments.customers
            and state["messages_without_a_turn"] == 0
            and state["conversations_by_replies_sent"] == {"1": arguments.customers}
        ),
    }


async def model_down(arguments: argparse.Namespace, secret: str) -> dict[str, Any]:
    sent: list[str] = []
    tenants = cycle(QUESTIONS)
    timeout = httpx.Timeout(30, read=None)
    await asyncio.to_thread(compose, "up", "-d", "--no-deps", "worker", environment=NOWHERE)
    try:
        async with httpx.AsyncClient(base_url=arguments.base_url, timeout=timeout) as client:
            answers = await asyncio.gather(
                *(
                    ask(client, secret, next(tenants), arguments.patience, sent)
                    for _ in range(arguments.customers)
                )
            )
    finally:
        # Back to what the stack was started with, whatever happened above.
        await asyncio.to_thread(compose, "up", "-d", "--no-deps", "worker")

    state = what_happened(sent)
    after: list[str] = []
    async with httpx.AsyncClient(base_url=arguments.base_url, timeout=timeout) as client:
        back, back_seconds = await ask(client, secret, "navalha", arguments.patience, after)
    told = [seconds for text, seconds in answers if text == HANDOFF_NOTICE]
    return {
        "scenario": "model-down",
        "customers": arguments.customers,
        "told_a_person_takes_over": len(told),
        "time_until_told": _seconds(told),
        "database": state,
        "after_the_worker_was_put_back": {
            "a_new_customer_was_answered": back is not None and back != HANDOFF_NOTICE,
            "in_s": round(back_seconds, 1),
        },
        "passed": (
            len(told) == arguments.customers
            and state["conversations_by_replies_sent"] == {"1": arguments.customers}
            and state["handoffs"] == {"agent_failed": arguments.customers}
            and state["model_calls"] == 0
            and back is not None
            and back != HANDOFF_NOTICE
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("scenario", choices=["worker-killed", "model-down"])
    parser.add_argument("--base-url", default="http://127.0.0.1:8700")
    parser.add_argument("--customers", type=int, default=12)
    parser.add_argument("--patience", type=float, default=420, help="how long a reply may take")
    parser.add_argument(
        "--kill-after", type=float, default=1.0, help="seconds between the burst and the kill"
    )
    parser.add_argument("--down", type=float, default=10, help="seconds the worker stays down")
    parser.add_argument("--out", type=Path, help="where to write the report as JSON")
    arguments = parser.parse_args()
    secret = os.environ.get("FRONTDESK_WEBCHAT_SECRET", DEFAULT_SECRET)

    scenario = worker_killed if arguments.scenario == "worker-killed" else model_down
    report = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        **asyncio.run(scenario(arguments, secret)),
    }
    text = json.dumps(report, indent=2) + "\n"
    if arguments.out:
        arguments.out.parent.mkdir(parents=True, exist_ok=True)
        arguments.out.write_text(text)
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
