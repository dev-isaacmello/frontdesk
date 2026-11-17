"""Table mappings. Constraints and row-level security live in the migrations."""

from datetime import datetime, time
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB, TSTZRANGE, Range
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _generated_id() -> Mapped[UUID]:
    return mapped_column(primary_key=True, server_default=text("uuidv7()"))


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = _generated_id()
    slug: Mapped[str]
    name: Mapped[str]
    timezone: Mapped[str]
    slot_minutes: Mapped[int]


class Resource(Base):
    """What gets booked: a professional or a court."""

    __tablename__ = "resources"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    name: Mapped[str]
    kind: Mapped[str]


class Service(Base):
    __tablename__ = "services"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    name: Mapped[str]
    duration_minutes: Mapped[int]


class ServiceResource(Base):
    __tablename__ = "service_resources"

    tenant_id: Mapped[UUID]
    service_id: Mapped[UUID] = mapped_column(primary_key=True)
    resource_id: Mapped[UUID] = mapped_column(primary_key=True)


class ServicePrice(Base):
    """The price of a service from a local time of day until the next row's time."""

    __tablename__ = "service_prices"

    tenant_id: Mapped[UUID]
    service_id: Mapped[UUID] = mapped_column(primary_key=True)
    starts_at: Mapped[time] = mapped_column(primary_key=True)
    price_cents: Mapped[int]


class BusinessHours(Base):
    """Opening hours of one ISO weekday. A weekday without a row is closed."""

    __tablename__ = "business_hours"

    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    weekday: Mapped[int] = mapped_column(primary_key=True)
    opens: Mapped[time]
    closes: Mapped[time]


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    display_name: Mapped[str | None]


class CustomerIdentity(Base):
    """How one channel names a customer."""

    __tablename__ = "customer_identities"

    tenant_id: Mapped[UUID] = mapped_column(primary_key=True)
    channel: Mapped[str] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(primary_key=True)
    customer_id: Mapped[UUID]
    phone: Mapped[str | None]


class ScheduleBlock(Base):
    """A period when a resource takes no bookings."""

    __tablename__ = "schedule_blocks"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    resource_id: Mapped[UUID]
    during: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    reason: Mapped[str | None]


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    customer_id: Mapped[UUID]
    service_id: Mapped[UUID]
    resource_id: Mapped[UUID]
    during: Mapped[Range[datetime]] = mapped_column(TSTZRANGE)
    status: Mapped[str] = mapped_column(server_default="confirmed")
    price_cents: Mapped[int]
    idempotency_key: Mapped[str]
    cancelled_at: Mapped[datetime | None]


class ChannelAccount(Base):
    """The address of a tenant on a channel, such as a WhatsApp phone number id."""

    __tablename__ = "channel_accounts"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    channel: Mapped[str]
    external_id: Mapped[str]


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    channel_account_id: Mapped[UUID]
    customer_id: Mapped[UUID]
    last_inbound_at: Mapped[datetime]


class InboundEvent(Base):
    __tablename__ = "inbound_events"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    channel_account_id: Mapped[UUID]
    provider_message_id: Mapped[str]
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Turn(Base):
    """One run of the agent over the customer messages that were waiting."""

    __tablename__ = "turns"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    conversation_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(server_default="running")
    outcome: Mapped[str | None]
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    conversation_id: Mapped[UUID]
    direction: Mapped[str]
    author: Mapped[str]
    body: Mapped[str]
    occurred_at: Mapped[datetime]
    turn_id: Mapped[UUID | None]
    inbound_event_id: Mapped[UUID | None]
    seq: Mapped[int | None]
    sent_at: Mapped[datetime | None]
    provider_message_id: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class ModelCall(Base):
    __tablename__ = "model_calls"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    turn_id: Mapped[UUID]
    node: Mapped[str]
    provider: Mapped[str]
    model: Mapped[str]
    input_tokens: Mapped[int]
    output_tokens: Mapped[int]
    cache_read_tokens: Mapped[int]
    cache_write_tokens: Mapped[int]
    latency_ms: Mapped[int]
    cost_microusd: Mapped[int]
    price_table_version: Mapped[str]
