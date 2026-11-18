"""Actions that wait for the owner: which ones, the requests, and the decisions."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import ApprovalRequest, Booking, Tenant, Turn

type Rule = Literal["late_change"]

_CHANGES = frozenset({"cancel_booking", "reschedule_booking"})


@dataclass(frozen=True)
class PendingApproval:
    """A tool call the turn stopped at, as the graph hands it to the worker."""

    rule: Rule
    tool: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Decided:
    approval_id: UUID
    turn_id: UUID
    approved: bool


@dataclass(frozen=True)
class ApprovalInfo:
    id: UUID
    conversation_id: UUID
    rule: Rule
    tool: str
    arguments: dict[str, Any]
    status: str
    requested_at: datetime


async def sensitive_rule(
    session: AsyncSession,
    tenant: Tenant,
    customer_id: UUID,
    tool: str,
    arguments: dict[str, Any],
    now: datetime,
) -> Rule | None:
    """The rule that makes this call wait for the owner, or None when it may run.

    Today there is one: cancelling or moving a booking of the customer that starts within
    the tenant's notice. A call on a booking that is not theirs is not sensitive; the tool
    refuses it by itself.
    """
    if tool not in _CHANGES or tenant.late_change_minutes is None:
        return None
    try:
        booking_id = UUID(str(arguments.get("booking_id")))
    except ValueError:
        return None
    booking = await session.scalar(
        select(Booking).where(
            Booking.id == booking_id,
            Booking.customer_id == customer_id,
            Booking.status == "confirmed",
        )
    )
    if booking is None:
        return None
    starts_at = booking.during.lower
    assert starts_at is not None, "a booking always has a start"
    notice = timedelta(minutes=tenant.late_change_minutes)
    return "late_change" if starts_at - now < notice else None


async def has_pending(session: AsyncSession, conversation_id: UUID) -> bool:
    found = await session.scalar(
        select(ApprovalRequest.id).where(
            ApprovalRequest.conversation_id == conversation_id, ApprovalRequest.status == "pending"
        )
    )
    return found is not None


async def request(
    session: AsyncSession,
    tenant_id: UUID,
    conversation_id: UUID,
    turn_id: UUID,
    pending: PendingApproval,
    now: datetime,
) -> None:
    session.add(
        ApprovalRequest(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            turn_id=turn_id,
            rule=pending.rule,
            tool=pending.tool,
            arguments=pending.arguments,
            requested_at=now,
        )
    )


async def decide(
    session: AsyncSession, approval_id: UUID, *, approved: bool, now: datetime
) -> UUID | None:
    """Records the owner's decision once. Returns the conversation to wake, or None when
    the request does not exist or was already decided."""
    conversation_id: UUID | None = await session.scalar(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == approval_id, ApprovalRequest.status == "pending")
        .values(status="approved" if approved else "rejected", decided_at=now)
        .returning(ApprovalRequest.conversation_id)
    )
    return conversation_id


async def next_decided(session: AsyncSession, conversation_id: UUID) -> Decided | None:
    """A decision whose paused turn has not been taken up again yet."""
    row = await session.scalar(
        select(ApprovalRequest)
        .join(Turn, Turn.id == ApprovalRequest.turn_id)
        .where(
            ApprovalRequest.conversation_id == conversation_id,
            ApprovalRequest.status.in_(("approved", "rejected")),
            ApprovalRequest.resumed_at.is_(None),
            Turn.status == "awaiting_approval",
        )
        .order_by(ApprovalRequest.decided_at)
        .limit(1)
    )
    if row is None:
        return None
    return Decided(approval_id=row.id, turn_id=row.turn_id, approved=row.status == "approved")


async def mark_resumed(session: AsyncSession, approval_id: UUID, now: datetime) -> None:
    await session.execute(
        update(ApprovalRequest).where(ApprovalRequest.id == approval_id).values(resumed_at=now)
    )


async def pending_of_tenant(session: AsyncSession) -> list[ApprovalInfo]:
    """The requests waiting for the owner, oldest first. The tenant is the session's."""
    rows = await session.scalars(
        select(ApprovalRequest)
        .where(ApprovalRequest.status == "pending")
        .order_by(ApprovalRequest.requested_at)
    )
    return [
        ApprovalInfo(
            id=row.id,
            conversation_id=row.conversation_id,
            rule=row.rule,  # type: ignore[arg-type]
            tool=row.tool,
            arguments=row.arguments,
            status=row.status,
            requested_at=row.requested_at,
        )
        for row in rows
    ]
