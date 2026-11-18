"""The HTTP application.

For a customer message it stores what arrives and enqueues, and never calls a model. The
owner's routes read and write the tenant's own data.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from frontdesk.api.deps import ApiDeps
from frontdesk.api.owner import owner_router
from frontdesk.api.webchat import webchat_router

__all__ = ["ApiDeps", "create_app"]


def create_app(deps: ApiDeps) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await deps.notifications.start()
        yield
        await deps.notifications.stop()
        await deps.queue.close()

    # The API is called by the panel's server and by channel providers, never by a
    # browser, so it publishes no interactive documentation.
    app = FastAPI(
        title="frontdesk", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.include_router(webchat_router(deps))
    app.include_router(owner_router(deps))

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
