"""Fixtures for the queue contract: each implementation, the real one in an emulator."""

import time
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
from testcontainers.core.container import DockerContainer
from testcontainers.core.network import Network

from frontdesk.queue.port import TriggerQueue
from frontdesk.queue.servicebus import ServiceBusTriggerQueue, connect
from tests.conftest import BACKEND_ROOT
from tests.fakes import InMemoryTriggerQueue

SERVICEBUS_IMAGE = "mcr.microsoft.com/azure-messaging/servicebus-emulator:2.0.1"
SQL_SERVER_IMAGE = "mcr.microsoft.com/mssql/server:2022-latest"
SQL_SERVER_PASSWORD = "Local-emulator-1"
SERVICEBUS_CONFIG = BACKEND_ROOT.parent / "ops" / "local" / "servicebus-emulator.json"


@pytest.fixture(scope="session")
def servicebus() -> Iterator[str]:
    """Microsoft's Service Bus emulator, with the queue the local stack also uses.

    It keeps its state in a SQL Server of its own and reads its queues from a file: the
    emulator does not create entities at runtime for this SDK. Yields a connection string.
    """
    with Network() as network:
        sql_server = (
            DockerContainer(SQL_SERVER_IMAGE)
            .with_network(network)
            .with_network_aliases("mssql")
            .with_env("ACCEPT_EULA", "Y")
            .with_env("MSSQL_SA_PASSWORD", SQL_SERVER_PASSWORD)
        )
        emulator = (
            DockerContainer(SERVICEBUS_IMAGE)
            .with_network(network)
            .with_env("ACCEPT_EULA", "Y")
            .with_env("SQL_SERVER", "mssql")
            .with_env("MSSQL_SA_PASSWORD", SQL_SERVER_PASSWORD)
            .with_env("SQL_WAIT_INTERVAL", "0")
            .with_volume_mapping(
                str(SERVICEBUS_CONFIG), "/ServiceBus_Emulator/ConfigFiles/Config.json", "ro"
            )
            .with_exposed_ports(5672, 5300)
        )
        with sql_server, emulator:
            host = emulator.get_container_host_ip()
            _wait_until_healthy(f"http://{host}:{emulator.get_exposed_port(5300)}/health")
            yield (
                f"Endpoint=sb://{host}:{emulator.get_exposed_port(5672)};"
                "SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=SAS_KEY_VALUE;"
                "UseDevelopmentEmulator=true;"
            )


def _wait_until_healthy(url: str, *, timeout_seconds: float = 180) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == httpx.codes.OK:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError(f"the Service Bus emulator was not healthy after {timeout_seconds} s")


@pytest.fixture(params=["memory", "servicebus"])
async def any_queue(request: pytest.FixtureRequest) -> AsyncIterator[TriggerQueue]:
    """Each implementation of the trigger queue in turn, for the contract tests."""
    if request.param == "memory":
        yield InMemoryTriggerQueue()
        return
    # No client-side retries, so that an empty queue answers within the wait asked for.
    client = connect(connection_string=request.getfixturevalue("servicebus"), retries=0)
    queue = ServiceBusTriggerQueue(client, "triggers")
    yield queue
    await _drain(queue)
    await queue.close()


async def _drain(queue: TriggerQueue) -> None:
    """Empties the emulator's one queue, which every test shares."""
    while (lease := await queue.lease(wait_seconds=0.2)) is not None:
        if (delivery := await lease.receive()) is not None:
            await lease.ack(delivery)
        await lease.release()
