"""Holds one web chat conversation with the running stack and prints what came back.

Runs against a stack that is already up (`docker compose up`). The messages go through
the same signed endpoint and event stream the panel uses, one after the other in a single
session, so later messages see the earlier ones as history.

    uv run python scripts/conversation.py "quanto custa o corte?" "tem horário amanhã às 10h?"

It asserts nothing: it is how I look at a real model answering, and where the numbers in
the measurements log for a real model come from. Tokens and cost of the same turns are in
the `model_calls` table.
"""

import argparse
import asyncio
import json
import os
import time
from datetime import UTC, datetime
from uuid import uuid4

import httpx

from frontdesk.channels.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, sign

DEFAULT_SECRET = "local-webchat-secret-change-me"  # noqa: S105  the compose default, not a secret


def signed(secret: str, method: str, path: str, body: bytes = b"") -> dict[str, str]:
    timestamp, signature = sign(secret, datetime.now(UTC), method, path, body)
    return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature}


async def say(
    client: httpx.AsyncClient,
    secret: str,
    tenant: str,
    session_id: str,
    text: str,
    after: str | None,
) -> tuple[str, str, float]:
    """Sends one message. Returns the reply, its event id and the seconds it took."""
    path = f"/channels/webchat/{tenant}/messages"
    body = json.dumps({"session_id": session_id, "message_id": uuid4().hex, "text": text}).encode()

    started = time.perf_counter()
    accepted = await client.post(path, content=body, headers=signed(secret, "POST", path, body))
    accepted.raise_for_status()
    conversation_id = accepted.json()["conversation_id"]

    events = f"/channels/webchat/{tenant}/conversations/{conversation_id}/events"
    events += f"?session_id={session_id}" + (f"&after={after}" if after else "")
    event_id = ""
    is_message = False
    async with client.stream("GET", events, headers=signed(secret, "GET", events)) as stream:
        stream.raise_for_status()
        async for line in stream.aiter_lines():
            if line.startswith("id: "):
                event_id = line.removeprefix("id: ")
            elif line.startswith("event: "):
                is_message = line == "event: message"
            elif line.startswith("data: ") and is_message:
                reply = json.loads(line.removeprefix("data: "))["text"]
                return reply, event_id, time.perf_counter() - started
    raise RuntimeError("the stream closed before the reply")


async def converse(base_url: str, secret: str, tenant: str, messages: list[str]) -> None:
    session_id = uuid4().hex
    after: str | None = None
    async with httpx.AsyncClient(base_url=base_url, timeout=180) as client:
        for text in messages:
            reply, after, seconds = await say(client, secret, tenant, session_id, text, after)
            print(f"> {text}\n< {reply}\n  ({seconds:.1f} s)\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("messages", nargs="+", help="what the customer says, in order")
    parser.add_argument("--base-url", default="http://127.0.0.1:8700")
    parser.add_argument("--tenant", default="navalha")
    arguments = parser.parse_args()
    secret = os.environ.get("FRONTDESK_WEBCHAT_SECRET", DEFAULT_SECRET)
    asyncio.run(converse(arguments.base_url, secret, arguments.tenant, arguments.messages))


if __name__ == "__main__":
    main()
