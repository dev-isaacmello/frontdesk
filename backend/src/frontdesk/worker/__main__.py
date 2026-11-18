"""Entry point of the worker: `python -m frontdesk.worker`."""

import asyncio
import logging
import signal

from frontdesk import logs, metrics, telemetry
from frontdesk.agent import checkpoints
from frontdesk.config import Settings
from frontdesk.wiring import queue_from, worker_from
from frontdesk.worker.loop import run

log = logging.getLogger("frontdesk.worker")


async def main() -> None:
    logs.configure()
    settings = Settings()
    telemetry.configure("frontdesk-worker", settings.otlp_endpoint)
    metrics.configure("frontdesk-worker", settings.otlp_metrics_endpoint)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)

    # The loop is what waits again when no conversation has work, not the SDK: its
    # retries would back off with nobody listening.
    queue = queue_from(settings, retries=0)
    log.info("worker_started", extra={"concurrency": settings.worker_concurrency})
    try:
        # Turns that stop for the owner's approval are kept in PostgreSQL, so the worker
        # that gets the decision can be another one.
        async with checkpoints.pool(settings.database_dsn) as paused_turns:
            deps = worker_from(settings, checkpoints.saver(paused_turns))
            await run(deps, queue, stop, concurrency=settings.worker_concurrency)
    finally:
        await queue.close()
    log.info("worker_stopped")


if __name__ == "__main__":
    asyncio.run(main())
