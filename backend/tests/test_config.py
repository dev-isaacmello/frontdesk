"""Configuration read from the environment."""

import pytest

from frontdesk.config import Settings

REQUIRED = {
    "FRONTDESK_DATABASE_URL": "postgresql+psycopg://app:secret@db:5432/frontdesk",
    "FRONTDESK_WEBCHAT_SECRET": "a-secret",
}


def test_the_defaults_run_the_offline_model(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)

    settings = Settings()

    assert (settings.model_provider, settings.model) == ("offline", "offline")
    assert settings.queue_name == "triggers"
    assert settings.database_dsn == "postgresql://app:secret@db:5432/frontdesk"


def test_a_variable_set_to_nothing_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose passes every variable through, empty when the developer did not set it."""
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("FRONTDESK_AZURE_OPENAI_ENDPOINT", "")
    monkeypatch.setenv("FRONTDESK_AZURE_OPENAI_API_KEY", "")
    monkeypatch.setenv("FRONTDESK_SERVICEBUS_NAMESPACE", "")

    settings = Settings()

    assert settings.azure_openai_endpoint is None
    assert settings.azure_openai_api_key is None
    assert settings.servicebus_namespace is None
