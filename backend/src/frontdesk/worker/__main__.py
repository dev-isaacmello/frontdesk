"""Entry point of the worker: `python -m frontdesk.worker`."""

import asyncio
import logging
import signal

from frontdesk import logs
from frontdesk.config import Settings
from frontdesk.wiring import queue_from, worker_from
from frontdesk.worker.loop import run

log = logging.getLogger("frontdesk.worker")


async def main() -> None:
    logs.configure()
    settings = Settings()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    # The loop is what waits again when no conversation has work, not the SDK: its
    # retries would back off with nobody listening.
    queue = queue_from(settings, retries=0)
    log.info("worker_started", extra={"concurrency": settings.worker_concurrency})
    try:
        await run(worker_from(settings), queue, stop, concurrency=settings.worker_concurrency)
    finally:
        await queue.close()
    log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
