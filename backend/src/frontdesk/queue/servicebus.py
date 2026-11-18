"""The trigger queue on Azure Service Bus.

The queue requires sessions and the session is the conversation: Service Bus gives a
session to one receiver at a time and keeps its messages in order, which is the lease the
port describes. Duplicate detection drops a second send with the same message id.

Each lease is a receiver of its own, opened when the session is accepted and closed when
the lease is released.
"""

import asyncio
import hashlib
import json
from uuid import UUID

from azure.servicebus import NEXT_AVAILABLE_SESSION, ServiceBusMessage, ServiceBusReceivedMessage
from azure.servicebus.aio import (
    AutoLockRenewer,
    ServiceBusClient,
    ServiceBusReceiver,
    ServiceBusSender,
)
from azure.servicebus.exceptions import OperationTimeoutError

from frontdesk.queue.port import Delivery
from frontdesk.queue.triggers import Trigger

_RECEIVE_WAIT_SECONDS = 5
_LOCK_RENEWAL_SECONDS = 300
"""How long a session is kept beyond the queue's lock duration: the longest turn allowed."""


def connect(
    *, connection_string: str | None = None, namespace: str | None = None, retries: int = 3
) -> ServiceBusClient:
    """A client from a connection string, for the emulator, or from the namespace's host
    name, signing in as the identity the process runs with.

    `retries` is how many times the SDK repeats a failed operation, which includes waiting
    again for a session when none was free.
    """
    if connection_string is not None:
        return ServiceBusClient.from_connection_string(connection_string, retry_total=retries)
    if namespace is None:
        raise ValueError("either a connection string or a namespace is required")
    from azure.identity.aio import DefaultAzureCredential

    return ServiceBusClient(namespace, DefaultAzureCredential(), retry_total=retries)


class ServiceBusLease:
    def __init__(self, receiver: ServiceBusReceiver) -> None:
        self._receiver = receiver

    async def receive(self) -> Delivery | None:
        # Asking for one message returns as soon as it arrives. Asking for more makes the
        # SDK wait a further 0.2 s for the rest of the batch, on every turn.
        messages = await self._receiver.receive_messages(
            max_message_count=1, max_wait_time=_RECEIVE_WAIT_SECONDS
        )
        if not messages:
            return None
        [message] = messages
        # Service Bus counts earlier deliveries that were abandoned, starting at zero.
        return Delivery(
            trigger=_parse(message), attempt=(message.delivery_count or 0) + 1, token=message
        )

    async def ack(self, delivery: Delivery) -> None:
        await self._receiver.complete_message(_message(delivery))

    async def retry(self, delivery: Delivery) -> None:
        # Abandoning counts a delivery. Past the queue's maximum delivery count, Service
        # Bus moves the message to the dead-letter queue.
        await self._receiver.abandon_message(_message(delivery))

    async def release(self) -> None:
        await self._receiver.close()


class ServiceBusTriggerQueue:
    def __init__(self, client: ServiceBusClient, queue_name: str) -> None:
        self._client = client
        self._queue_name = queue_name
        self._sender: ServiceBusSender | None = None
        # The SDK's sender is not safe to share between coroutines: two sends racing to
        # open it break each other. One sender, one send at a time.
        self._sending = asyncio.Lock()
        self._renewer = AutoLockRenewer(max_lock_renewal_duration=_LOCK_RENEWAL_SECONDS)

    async def send(self, trigger: Trigger, *, deduplication_id: str) -> None:
        body = json.dumps(
            {
                "tenant_id": str(trigger.tenant_id),
                "conversation_id": str(trigger.conversation_id),
                "traceparent": trigger.traceparent,
            }
        )
        message = ServiceBusMessage(
            body,
            session_id=str(trigger.conversation_id),
            # Hashed because Service Bus limits a message id to 128 characters.
            message_id=hashlib.sha256(deduplication_id.encode()).hexdigest(),
        )
        async with self._sending:
            if self._sender is None:
                self._sender = self._client.get_queue_sender(self._queue_name)
            await self._sender.send_messages(message)

    async def lease(self, *, wait_seconds: float) -> ServiceBusLease | None:
        receiver = self._client.get_queue_receiver(
            self._queue_name,
            session_id=NEXT_AVAILABLE_SESSION,
            max_wait_time=wait_seconds,
            auto_lock_renewer=self._renewer,
        )
        try:
            await receiver.__aenter__()
        except OperationTimeoutError:
            # No session with messages was free within the wait.
            await receiver.close()
            return None
        except BaseException:
            await receiver.close()
            raise
        return ServiceBusLease(receiver)

    async def close(self) -> None:
        await self._renewer.close()
        await self._client.close()


def _parse(message: ServiceBusReceivedMessage) -> Trigger:
    fields = json.loads(str(message))
    return Trigger(
        tenant_id=UUID(fields["tenant_id"]),
        conversation_id=UUID(fields["conversation_id"]),
        traceparent=fields.get("traceparent"),
    )


def _message(delivery: Delivery) -> ServiceBusReceivedMessage:
    assert isinstance(delivery.token, ServiceBusReceivedMessage)
    return delivery.token
