"""Tells the owner which of their rules contradict the policy that is enforced in code.

This is a convenience for the owner and nothing else. A rule that offers a discount fails
when a reply is validated, whether or not this check noticed it (ADR 0007).
"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from frontdesk.agent import prompts
from frontdesk.agent.graph import AgentDeps
from frontdesk.db.session import tenant_transaction
from frontdesk.domain.rules import Finding, active_rules, replace_findings
from frontdesk.policy.output import discount_offers
from frontdesk.providers.port import Message, ModelRequest


class _Reported(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clause: Literal["discount", "price_outside_catalog", "action_without_tool", "outside_business"]
    excerpt: str


class _Report(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[_Reported]


async def check_rules(deps: AgentDeps, tenant_id: UUID) -> list[Finding]:
    """Checks the version in force, stores its findings and returns them."""
    async with tenant_transaction(deps.sessions, tenant_id) as session:
        rules = await active_rules(session, tenant_id)
    if rules is None:
        return []

    findings = _by_the_words(rules.body)
    for reported in await _by_the_model(deps, tenant_id, rules.body):
        finding = Finding(reported.clause, reported.excerpt.strip(), "model")
        # The model has to quote the owner. A finding it cannot point at is not shown.
        quoted = finding.excerpt and finding.excerpt in rules.body
        known = any((f.clause, f.excerpt) == (finding.clause, finding.excerpt) for f in findings)
        if quoted and not known:
            findings.append(finding)

    async with tenant_transaction(deps.sessions, tenant_id) as session:
        await replace_findings(session, tenant_id, rules, findings)
    return findings


def _by_the_words(body: str) -> list[Finding]:
    """What the same code that validates replies finds in the rules themselves."""
    return [
        Finding("discount", line.strip(), "code")
        for line in body.splitlines()
        if line.strip() and discount_offers(line)
    ]


async def _by_the_model(deps: AgentDeps, tenant_id: UUID, body: str) -> list[_Reported]:
    response = await deps.provider.complete(
        ModelRequest(
            model=deps.model,
            system=prompts.RULE_CHECK,
            messages=(Message(role="user", content=body),),
            output_schema=_Report.model_json_schema(),
            max_output_tokens=2048,
            reasoning_effort="low",
            timeout_s=30,
        )
    )
    await deps.ledger.record(
        tenant_id=tenant_id,
        turn_id=None,
        node="rule_check",
        provider=deps.provider.name,
        response=response,
    )
    return _Report.model_validate_json(response.text or "").findings
