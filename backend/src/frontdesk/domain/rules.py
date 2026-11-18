"""The owner's house rules: append-only versions, and what each version contradicts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from frontdesk.db.models import HouseRules, RuleFinding

type Clause = Literal[
    "discount", "price_outside_catalog", "action_without_tool", "outside_business"
]


@dataclass(frozen=True)
class RuleVersion:
    id: UUID
    version: int
    body: str
    created_at: datetime


@dataclass(frozen=True)
class Finding:
    clause: Clause
    excerpt: str
    source: Literal["code", "model"]


async def save_rules(
    session: AsyncSession, tenant_id: UUID, body: str, now: datetime
) -> RuleVersion:
    """Adds a version. It is in force from the next turn of every conversation."""
    latest = await session.scalar(
        select(func.max(HouseRules.version)).where(HouseRules.tenant_id == tenant_id)
    )
    row = HouseRules(tenant_id=tenant_id, version=(latest or 0) + 1, body=body, created_at=now)
    session.add(row)
    await session.flush()
    return RuleVersion(row.id, row.version, row.body, row.created_at)


async def active_rules(session: AsyncSession, tenant_id: UUID) -> RuleVersion | None:
    row = await session.scalar(
        select(HouseRules)
        .where(HouseRules.tenant_id == tenant_id)
        .order_by(HouseRules.version.desc())
        .limit(1)
    )
    return None if row is None else RuleVersion(row.id, row.version, row.body, row.created_at)


async def replace_findings(
    session: AsyncSession, tenant_id: UUID, rules: RuleVersion, findings: list[Finding]
) -> None:
    await session.execute(delete(RuleFinding).where(RuleFinding.house_rules_id == rules.id))
    session.add_all(
        RuleFinding(
            tenant_id=tenant_id,
            house_rules_id=rules.id,
            clause=finding.clause,
            excerpt=finding.excerpt,
            source=finding.source,
        )
        for finding in findings
    )


async def findings_of(session: AsyncSession, tenant_id: UUID) -> list[Finding]:
    """The findings of the version in force."""
    rules = await active_rules(session, tenant_id)
    if rules is None:
        return []
    rows = await session.scalars(
        select(RuleFinding).where(RuleFinding.house_rules_id == rules.id).order_by(RuleFinding.id)
    )
    return [Finding(row.clause, row.excerpt, row.source) for row in rows]  # type: ignore[arg-type]
