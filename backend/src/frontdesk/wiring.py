"""The composition root: where configuration becomes the objects the services run on."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI
from langgraph.checkpoint.base import BaseCheckpointSaver
from openai import AsyncOpenAI
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from frontdesk.agent.graph import AgentDeps
from frontdesk.agent.router import Routes
from frontdesk.api.app import ApiDeps, create_app
from frontdesk.channels.port import ChannelSender
from frontdesk.channels.webchat import PostgresNotifications, WebchatSender
from frontdesk.channels.whatsapp import WhatsAppSender
from frontdesk.config import Settings
from frontdesk.db.session import SessionFactory, create_engine, create_session_factory
from frontdesk.domain.customers import Channel
from frontdesk.providers.azure_openai import AzureOpenAIProvider
from frontdesk.providers.embeddings import AzureOpenAIEmbedder, Embedder, HashingEmbedder
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
    return azure_openai_provider(settings.azure_openai_endpoint, settings.azure_openai_api_key)


def azure_openai_provider(endpoint: str, key: SecretStr | None) -> AzureOpenAIProvider:
    """The adapter for a resource, signing in with the key or, without one, as the process."""
    return AzureOpenAIProvider(_azure_client(endpoint, key), reasoning_models=reasoning_models())


def azure_openai_embedder(endpoint: str, key: SecretStr | None, model: str) -> AzureOpenAIEmbedder:
    return AzureOpenAIEmbedder(_azure_client(endpoint, key), model)


def embedder_from(settings: Settings) -> Embedder:
    """The embedder of the knowledge base: offline unless a deployment is named."""
    if settings.embedding_model == "offline":
        return HashingEmbedder()
    if settings.azure_openai_endpoint is None:
        raise ValueError("FRONTDESK_AZURE_OPENAI_ENDPOINT is required for an embedding model")
    return azure_openai_embedder(
        settings.azure_openai_endpoint, settings.azure_openai_api_key, settings.embedding_model
    )


class _ModelAccess(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FRONTDESK_", extra="ignore", env_parse_none_str=""
    )

    azure_openai_endpoint: str
    azure_openai_api_key: SecretStr | None = None


def model_access_from_env(env_file: Path | None = None) -> tuple[str, SecretStr | None]:
    """The endpoint and key of the model resource, for scripts that need nothing else."""
    access = _ModelAccess(_env_file=env_file)
    return access.azure_openai_endpoint, access.azure_openai_api_key


def _azure_client(endpoint: str, key: SecretStr | None) -> AsyncOpenAI:
    return AsyncOpenAI(
        # The v1 route, where the model named in a request is the deployment.
        base_url=f"{endpoint.rstrip('/')}/openai/v1/",
        api_key=key.get_secret_value() if key else _entra_token_provider(),
        # The SDK retries nothing. A throttled call is made again by the graph, which knows
        # how long it may wait, and any other failure is the worker's, as a whole turn.
        max_retries=0,
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
            whatsapp_app_secret=_revealed(settings.whatsapp_app_secret),
            whatsapp_verify_token=_revealed(settings.whatsapp_verify_token),
            # Used only to check the owner's rules when they are saved.
            agent=AgentDeps(
                sessions=sessions,
                provider=provider_from(settings),
                model=settings.model,
                ledger=ModelLedger(sessions, load_price_table()),
            ),
        )
    )


def _revealed(secret: SecretStr | None) -> str | None:
    return secret.get_secret_value() if secret else None


def _senders(settings: Settings, sessions: SessionFactory) -> dict[Channel, ChannelSender]:
    senders: dict[Channel, ChannelSender] = {"webchat": WebchatSender(sessions)}
    if settings.whatsapp_access_token:
        senders["whatsapp"] = WhatsAppSender(
            # Its timeout is set on each request.
            httpx.AsyncClient(),
            sessions,
            settings.whatsapp_access_token,
            clock=now,
            sleep=asyncio.sleep,
        )
    return senders


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
            embedder=embedder_from(settings),
            routes=Routes(
                default=settings.model,
                classify=settings.model_classify,
                pro=settings.model_pro,
                economy=settings.model_economy,
            ),
            daily_cap_microusd=(
                None
                if settings.daily_cap_usd is None
                else round(settings.daily_cap_usd * 1_000_000)
            ),
            checkpointer=checkpointer,
        ),
        senders=_senders(settings, sessions),
        clock=now,
        quiet_window=timedelta(seconds=settings.quiet_window_seconds),
    )
