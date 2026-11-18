"""Configuration, read from the environment. See .env.example for every variable."""

from decimal import Decimal
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import make_url


class Settings(BaseSettings):
    # A variable set to nothing is the same as one that is not set.
    model_config = SettingsConfigDict(
        env_prefix="FRONTDESK_", extra="ignore", env_parse_none_str=""
    )

    database_url: str
    """SQLAlchemy URL of the application role, which is subject to row-level security."""

    queue_name: str = "triggers"
    servicebus_namespace: str | None = None
    """Host name of the Service Bus namespace, <name>.servicebus.windows.net. In Azure the
    process signs in with its managed identity, so there is no secret to hold."""

    servicebus_connection_string: SecretStr | None = None
    """Set only for the emulator, which accepts nothing else."""

    worker_concurrency: int = 6
    """Conversations one worker handles side by side. Each holds a connection to the
    queue while it is handled. The emulator allows ten connections in all, the API's
    included; a Standard namespace allows a thousand."""

    quiet_window_seconds: float = 1.5
    """How long a customer has to be silent before the agent answers. A burst of short
    messages inside it becomes one turn."""

    webchat_secret: SecretStr
    """Shared with the panel's server, which signs every request it makes to the API."""

    model_provider: Literal["offline", "azure_openai"] = "offline"
    model: str = "offline"
    """The model to call: the deployment name on Azure OpenAI. It is also the price table key."""

    model_classify: str | None = None
    """A model for the classifier alone. The default model when unset."""

    model_pro: str | None = None
    """The planner's model for tenants on the pro plan. The default model when unset."""

    model_economy: str | None = None
    """The model of a tenant that reached its monthly budget. The default model when unset."""

    daily_cap_usd: Decimal | None = Decimal(2)
    """What every tenant together may spend on models in a day. Past it, turns go to a
    person until the next day. Unset means no cap."""

    embedding_model: str = "offline"
    """What the knowledge base is embedded and searched with: the offline word hashing, or
    the name of an embedding deployment on the same Azure OpenAI resource."""

    whatsapp_app_secret: SecretStr | None = None
    """The secret of the Meta app, which signs every webhook notification."""

    whatsapp_verify_token: SecretStr | None = None
    """Chosen here and typed into Meta's dashboard when the webhook is subscribed."""

    whatsapp_access_token: SecretStr | None = None
    """What the worker sends messages with. Without it the worker has no WhatsApp sender."""

    otlp_endpoint: str | None = None
    """Where spans are sent, as a full OTLP HTTP URL ending in /v1/traces. Unset, no span
    leaves the process."""

    azure_openai_endpoint: str | None = None
    """The resource endpoint, for example https://<resource>.openai.azure.com."""

    azure_openai_api_key: SecretStr | None = None
    """For local use. Left unset in Azure, where the managed identity is used instead."""

    @property
    def database_dsn(self) -> str:
        """The same database as a libpq connection string, for the notification listener."""
        url = make_url(self.database_url).set(drivername="postgresql")
        return url.render_as_string(hide_password=False)
