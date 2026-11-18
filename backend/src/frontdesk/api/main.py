"""Entry point of the API: `uvicorn --factory frontdesk.api.main:create`."""

from fastapi import FastAPI

from frontdesk import logs, metrics, telemetry
from frontdesk.config import Settings
from frontdesk.wiring import api_from


def create() -> FastAPI:
    logs.configure()
    settings = Settings()
    telemetry.configure("frontdesk-api", settings.otlp_endpoint)
    metrics.configure("frontdesk-api", settings.otlp_metrics_endpoint)
    return api_from(settings)
