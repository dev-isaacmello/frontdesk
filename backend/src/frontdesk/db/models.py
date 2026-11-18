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
    late_change_minutes: Mapped[int | None]


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
    mode: Mapped[str] = mapped_column(server_default="agent")
    lease_epoch: Mapped[int] = mapped_column(server_default="0")
    lease_until: Mapped[datetime | None]


class Handoff(Base):
    """A conversation that went to a person, and why."""

    __tablename__ = "handoffs"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    conversation_id: Mapped[UUID]
    turn_id: Mapped[UUID | None]
    reason: Mapped[str]
    opened_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None]


class User(Base):
    """An owner account. Created by the seed; there is no signup."""

    __tablename__ = "users"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    email: Mapped[str]
    name: Mapped[str]
    password_hash: Mapped[str]


class OwnerSession(Base):
    __tablename__ = "owner_sessions"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    user_id: Mapped[UUID]
    token_hash: Mapped[str]
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]


class TurnStep(Base):
    """One node of the graph as it ran in a turn."""

    __tablename__ = "turn_steps"

    turn_id: Mapped[UUID] = mapped_column(primary_key=True)
    seq: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[UUID]
    node: Mapped[str]
    duration_ms: Mapped[int]
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ApprovalRequest(Base):
    """A tool call that waits for the owner before it runs."""

    __tablename__ = "approval_requests"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    conversation_id: Mapped[UUID]
    turn_id: Mapped[UUID]
    rule: Mapped[str]
    tool: Mapped[str]
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(server_default="pending")
    requested_at: Mapped[datetime]
    decided_at: Mapped[datetime | None]
    resumed_at: Mapped[datetime | None]


class HouseRules(Base):
    """One version of the free text the owner writes. The newest is in force."""

    __tablename__ = "house_rules"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    version: Mapped[int]
    body: Mapped[str]
    created_at: Mapped[datetime]


class RuleFinding(Base):
    """Where a version of the rules contradicts the policy enforced in code."""

    __tablename__ = "rule_findings"

    id: Mapped[UUID] = _generated_id()
    tenant_id: Mapped[UUID]
    house_rules_id: Mapped[UUID]
    clause: Mapped[str]
    excerpt: Mapped[str]
    source: Mapped[str]


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
    blocked_drafts: Mapped[int] = mapped_column(server_default="0")


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
    turn_id: Mapped[UUID | None]
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
