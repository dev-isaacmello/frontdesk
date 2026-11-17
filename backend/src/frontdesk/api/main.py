"""Entry point of the API: `uvicorn --factory frontdesk.api.main:create`."""

from fastapi import FastAPI

from frontdesk import logs
from frontdesk.config import Settings
from frontdesk.wiring import api_from


def create() -> FastAPI:
    logs.configure()
    return api_from(Settings())
