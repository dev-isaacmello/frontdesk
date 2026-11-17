"""The trigger queue contract, held against Azure Service Bus and the in-memory stand-in.

Service Bus runs in Microsoft's emulator. The stand-in is what the API and worker tests
use, so it has to behave the same way in everything those tests rely on.
"""

import asyncio
from uuid import UUID, uuid4

from frontdesk.queue.port import Delivery, Lease, TriggerQueue
from frontdesk.queue.triggers import Trigger

TENANT = uuid4()
WAIT = 0.3
MAX_DELIVERIES = 5


def trigger(conversation_id: UUID | None = None) -> Trigger:
    return Trigger(tenant_id=TENANT, conversation_id=conversation_id or uuid4())


def event() -> str:
    """A deduplication id no other test has used: the emulator's queue is shared."""
    return f"event-{uuid4()}"


async def take(queue: TriggerQueue) -> Lease:
    lease = await queue.lease(wait_seconds=5)
    assert lease is not None
    return lease


async def next_of(lease: Lease) -> Delivery:
    delivery = await lease.receive()
    assert delivery is not None
    return delivery


async def test_a_trigger_is_delivered_until_it_is_acknowledged(any_queue: TriggerQueue) -> None:
    sent = trigger()
    await any_queue.send(sent, deduplication_id=event())

    lease = await take(any_queue)
    delivery = await next_of(lease)
    await lease.ack(delivery)
    await lease.release()

    assert delivery.trigger == sent
    assert delivery.attempt == 1
    assert await any_queue.lease(wait_seconds=WAIT) is None


async def test_ing_4_a_conversation_is_held_by_one_lease_at_a_time(any_queue: TriggerQueue) -> None:
    conversation = uuid4()
    await any_queue.send(trigger(conversation), deduplication_id=event())
    await any_queue.send(trigger(conversation), deduplication_id=event())

    holder = await take(any_queue)
    second = await any_queue.lease(wait_seconds=WAIT)
    first_trigger = await next_of(holder)
    await holder.ack(first_trigger)
    second_trigger = await next_of(holder)
    await holder.ack(second_trigger)
    await holder.release()

    assert second is None
    assert first_trigger.trigger.conversation_id == conversation
    assert second_trigger.trigger.conversation_id == conversation


async def test_ing_4_other_conversations_are_leased_meanwhile(any_queue: TriggerQueue) -> None:
    busy, other = uuid4(), uuid4()
    await any_queue.send(trigger(busy), deduplication_id=event())
    holder = await take(any_queue)

    await any_queue.send(trigger(other), deduplication_id=event())
    meanwhile = await take(any_queue)
    delivery = await next_of(meanwhile)

    assert delivery.trigger.conversation_id == other
    await meanwhile.release()
    await holder.release()


async def test_the_same_event_enqueued_twice_is_delivered_once(any_queue: TriggerQueue) -> None:
    sent, event_id = trigger(), event()
    await any_queue.send(sent, deduplication_id=event_id)
    await any_queue.send(sent, deduplication_id=event_id)

    lease = await take(any_queue)
    await lease.ack(await next_of(lease))
    await lease.release()

    assert await any_queue.lease(wait_seconds=WAIT) is None


async def test_a_trigger_released_without_an_answer_comes_back(any_queue: TriggerQueue) -> None:
    sent = trigger()
    await any_queue.send(sent, deduplication_id=event())
    crashed = await take(any_queue)
    await next_of(crashed)
    await crashed.release()

    lease = await take(any_queue)
    again = await next_of(lease)

    assert again.trigger == sent
    assert again.attempt == 1
    await lease.release()


async def test_a_retried_trigger_comes_back_counting_the_attempt(any_queue: TriggerQueue) -> None:
    await any_queue.send(trigger(), deduplication_id=event())
    failing = await take(any_queue)
    first = await next_of(failing)
    await failing.retry(first)
    await failing.release()

    lease = await take(any_queue)
    second = await next_of(lease)

    assert (first.attempt, second.attempt) == (1, 2)
    await lease.release()


async def test_a_trigger_that_keeps_failing_is_set_aside(any_queue: TriggerQueue) -> None:
    await any_queue.send(trigger(), deduplication_id=event())

    for _ in range(MAX_DELIVERIES):
        lease = await take(any_queue)
        delivery = await next_of(lease)
        await lease.retry(delivery)
        await lease.release()

    assert await any_queue.lease(wait_seconds=WAIT) is None


async def test_a_waiting_lease_wakes_when_a_trigger_arrives(any_queue: TriggerQueue) -> None:
    sent = trigger()
    waiting = asyncio.create_task(any_queue.lease(wait_seconds=10))
    await asyncio.sleep(0.2)

    await any_queue.send(sent, deduplication_id=event())
    lease = await asyncio.wait_for(waiting, timeout=5)

    assert lease is not None
    delivery = await next_of(lease)
    assert delivery.trigger == sent
    await lease.release()


async def test_triggers_sent_at_the_same_time_all_arrive(any_queue: TriggerQueue) -> None:
    conversations = {uuid4() for _ in range(8)}

    await asyncio.gather(
        *(any_queue.send(trigger(each), deduplication_id=event()) for each in conversations)
    )
    arrived = set()
    for _ in conversations:
        lease = await take(any_queue)
        delivery = await next_of(lease)
        await lease.ack(delivery)
        await lease.release()
        arrived.add(delivery.trigger.conversation_id)

    assert arrived == conversations
