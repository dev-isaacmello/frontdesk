"""The composition root: where configuration becomes the objects the services run on."""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from langgraph.checkpoint.base import BaseCheckpointSaver
from openai import AsyncOpenAI

from frontdesk.agent.graph import AgentDeps
from frontdesk.api.app import ApiDeps, create_app
from frontdesk.channels.webchat import PostgresNotifications, WebchatSender
from frontdesk.config import Settings
from frontdesk.db.session import SessionFactory, create_engine, create_session_factory
from frontdesk.providers.azure_openai import AzureOpenAIProvider
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.offline import OfflineProvider
from frontdesk.providers.port import ModelProvider
from frontdesk.providers.prices import load_price_table, reasoning_models
from frontdesk.queue.port import TriggerQueue
from frontdesk.queue.servicebus import ServiceBusTriggerQueue, connect
from frontdesk.worker.handler import WorkerDeps

AZURE_AI_SCOPE = "https://ai.azure.com/.default"


def now() -> datetime:
    return datetime.now(UTC)


def sessions_from(settings: Settings) -> SessionFactory:
    return create_session_factory(create_engine(settings.database_url))


def queue_from(settings: Settings, *, retries: int = 3) -> TriggerQueue:
    secret = settings.servicebus_connection_string
    client = connect(
        connection_string=secret.get_secret_value() if secret else None,
        namespace=settings.servicebus_namespace,
        retries=retries,
    )
    return ServiceBusTriggerQueue(client, settings.queue_name)


def provider_from(settings: Settings) -> ModelProvider:
    if settings.model_provider == "offline":
        return OfflineProvider()
    if settings.azure_openai_endpoint is None:
        raise ValueError("FRONTDESK_AZURE_OPENAI_ENDPOINT is required for azure_openai")
    key = settings.azure_openai_api_key
    return AzureOpenAIProvider(
        AsyncOpenAI(
            # The v1 route, where the model named in a request is the deployment.
            base_url=f"{settings.azure_openai_endpoint.rstrip('/')}/openai/v1/",
            api_key=key.get_secret_value() if key else _entra_token_provider(),
            # One retry policy for the whole turn, in the worker, not one per call here.
            max_retries=0,
        ),
        reasoning_models=reasoning_models(),
    )


def _entra_token_provider() -> Callable[[], Awaitable[str]]:
    from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

    return get_bearer_token_provider(DefaultAzureCredential(), AZURE_AI_SCOPE)


def api_from(settings: Settings) -> FastAPI:
    sessions = sessions_from(settings)
    return create_app(
        ApiDeps(
            sessions=sessions,
            queue=queue_from(settings),
            notifications=PostgresNotifications(settings.database_dsn),
            webchat_secret=settings.webchat_secret.get_secret_value(),
            clock=now,
            # Used only to check the owner's rules when they are saved.
            agent=AgentDeps(
                sessions=sessions,
                provider=provider_from(settings),
                model=settings.model,
                ledger=ModelLedger(sessions, load_price_table()),
            ),
        )
    )


def worker_from(settings: Settings, checkpointer: BaseCheckpointSaver[str]) -> WorkerDeps:
    """The worker's dependencies. The checkpointer's pool is opened and closed by the caller."""
    sessions = sessions_from(settings)
    return WorkerDeps(
        sessions=sessions,
        agent=AgentDeps(
            sessions=sessions,
            provider=provider_from(settings),
            model=settings.model,
            ledger=ModelLedger(sessions, load_price_table()),
            checkpointer=checkpointer,
        ),
        senders={"webchat": WebchatSender(sessions)},
        clock=now,
        quiet_window=timedelta(seconds=settings.quiet_window_seconds),
    )
