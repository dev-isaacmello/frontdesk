"""The turn as an explicit graph (docs/design/agent-graph.md).

    load_context -> classify -> retrieve -> plan -> gate -> execute -> plan
               \\           \\      \\       \\-> await_approval (interrupt) -> execute or plan
               \\           \\      \\-> validate -> done, back to plan once, or handoff
                \\           \\-> refuse
                 \\-> handoff

The planner's last message, the one without tool calls, is the reply. Persisting it and
sending it belong to the worker, so the graph knows nothing about channels.
"""

import datetime as dt
import inspect
import json
import operator
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Annotated, Any, Literal, Protocol, TypedDict
from zoneinfo import ZoneInfo

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict

from frontdesk.agent import intents, prompts
from frontdesk.agent.review import review
from frontdesk.agent.router import BudgetLevel, Routes
from frontdesk.agent.tool_runner import run_tool_call
from frontdesk.agent.turn import HandoffReason, HistoryMessage, Step, TurnInput, TurnResult
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain import approvals, budget, knowledge
from frontdesk.domain.approvals import PendingApproval
from frontdesk.domain.clock import to_local
from frontdesk.domain.rules import active_rules
from frontdesk.domain.tenants import load_tenant, opening_hours, timezone_of
from frontdesk.guardrail import Day, Sourced, facts_in
from frontdesk.providers.embeddings import Embedder
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.port import (
    Message,
    ModelError,
    ModelFilteredError,
    ModelProvider,
    ModelRequest,
    ModelResponse,
)
from frontdesk.tools.registry import TOOL_SPECS

__all__ = [
    "AgentDeps",
    "HistoryMessage",
    "TurnInput",
    "TurnLimits",
    "TurnResult",
    "resume_turn",
    "run_turn",
]

# A backstop above the counted limits below, which are the ones that act: they end the
# turn in handoff, where this one would raise.
_RECURSION_LIMIT = 60


@dataclass(frozen=True)
class TurnLimits:
    """Where a turn stops and goes to a person, however the model behaves."""

    tool_rounds: int = 6
    model_calls: int = 10
    tokens: int = 120_000
    """Input and output of every model call of the turn, added up."""


@dataclass(frozen=True)
class AgentDeps:
    sessions: SessionFactory
    provider: ModelProvider
    model: str
    ledger: ModelLedger
    limits: TurnLimits = TurnLimits()
    routes: Routes | None = None
    """Which model answers which node. Without routes every call goes to `model`."""
    daily_cap_microusd: int | None = None
    """What every tenant together may spend on models in a day. Past it, turns go to a person."""
    embedder: Embedder | None = None
    """What the customer's message is embedded with to search the knowledge base. Without
    one the turn runs with no retrieval."""
    checkpointer: BaseCheckpointSaver[str] = field(default_factory=InMemorySaver)
    """Where a turn that stops for approval is kept. In memory unless one is given, which
    is enough for a turn that starts and ends in the same process."""


class Classification(BaseModel):
    # Closed to extra fields, which strict structured output requires of the schema.
    model_config = ConfigDict(extra="forbid")

    in_scope: bool
    wants_human: bool


class _State(TypedDict, total=False):
    turn: TurnInput
    tenant_name: str
    plan_system: str
    in_scope: bool
    handoff_reason: HandoffReason
    transcript: Annotated[list[Message], operator.add]
    model_calls: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    tool_rounds: Annotated[int, operator.add]
    timezone: str
    today: dt.date
    facts: Annotated[list[Sourced], operator.add]
    """The ledger of the turn: every value a reply may state, with where it came from."""
    effects: Annotated[list[str], operator.add]
    draft: str
    blocks: Annotated[int, operator.add]
    gate: Literal["allow", "wait", "deny"]
    approval: dict[str, Any]
    steps: Annotated[list[dict[str, Any]], operator.add]
    knowledge: str
    tenant_plan: str
    budget_level: BudgetLevel
    """What was retrieved from the tenant's knowledge base for this turn."""
    outcome: Literal["replied", "refused", "handoff"]
    reply: str


async def run_turn(deps: AgentDeps, turn: TurnInput) -> TurnResult:
    # A retried turn starts over. Whatever an earlier attempt left on its thread is dropped
    # first, so that the graph is never handed new input on top of a paused run.
    await deps.checkpointer.adelete_thread(str(turn.turn_id))
    return await _run(deps, turn, {"turn": turn, "transcript": []})


async def resume_turn(deps: AgentDeps, turn: TurnInput, *, approved: bool) -> TurnResult:
    """Takes up a turn that stopped for approval, with the owner's decision."""
    return await _run(deps, turn, Command(resume=approved))


async def _run(deps: AgentDeps, turn: TurnInput, graph_input: _State | Command[Any]) -> TurnResult:
    thread = str(turn.turn_id)
    final = await _compiled(deps.checkpointer).ainvoke(
        graph_input,
        config={"recursion_limit": _RECURSION_LIMIT, "configurable": {"thread_id": thread}},
        context=deps,
        # One checkpoint, when the run stops. A turn that crashes is run again from its
        # start, with the same idempotency keys, so nothing in between has to be kept.
        durability="exit",
    )
    steps = tuple(Step(**step) for step in final.get("steps", []))
    waiting = final.get("__interrupt__")
    if waiting:
        return TurnResult(
            outcome="awaiting_approval",
            reply=prompts.WAIT_NOTICE,
            approval=PendingApproval(**waiting[0].value),
            steps=steps,
        )
    await deps.checkpointer.adelete_thread(thread)
    return TurnResult(
        outcome=final["outcome"],
        reply=final["reply"],
        handoff_reason=final.get("handoff_reason") if final["outcome"] == "handoff" else None,
        blocks=final.get("blocks", 0),
        steps=steps,
    )


async def _load_context(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    deps, turn = runtime.context, state["turn"]
    async with tenant_transaction(deps.sessions, turn.tenant_id) as session:
        tenant = await load_tenant(session, turn.tenant_id)
        hours = await opening_hours(session, turn.tenant_id)
        rules = await active_rules(session, turn.tenant_id)
        level = await budget.tenant_level(session, tenant, turn.now)
        open_for_calls = await budget.deployment_open(session, deps.daily_cap_microusd)
    local_now = to_local(turn.now, timezone_of(tenant))
    today = local_now.date()
    context: _State = {
        "tenant_name": tenant.name,
        "plan_system": prompts.plan_prompt(
            tenant.name, local_now, hours, rules.body if rules else None
        ),
        "transcript": [*_history(turn), Message(role="user", content="\n".join(turn.messages))],
        "timezone": tenant.timezone,
        "today": today,
        "tenant_plan": tenant.plan,
        "budget_level": level,
        "facts": [
            Sourced(Day(today), "profile"),
            *facts_in(prompts.opening_hours_text(hours), "profile", today=today),
            *(facts_in(rules.body, "rules", today=today) if rules else ()),
            *_said_by_the_customer(turn, today),
        ],
    }
    # Decided here, by matching, so that no wording in the rest of the message and no
    # answer of a model can keep a customer from reaching a person.
    if intents.asks_for_a_person(turn.messages):
        context["handoff_reason"] = "customer_asked"
    elif level == "exhausted" or not open_for_calls:
        # No model is called for a tenant past its budget, or for anyone once the
        # deployment reached its cap for the day or was switched off by hand.
        context["handoff_reason"] = "budget_exhausted"
    return context


def _model(deps: AgentDeps, state: _State, node: Literal["classify", "plan"]) -> str:
    routes = deps.routes or Routes(default=deps.model)
    return routes.model_for(node, state["tenant_plan"], state["budget_level"])


async def _call_model(
    deps: AgentDeps, turn: TurnInput, node: str, request: ModelRequest
) -> ModelResponse:
    """The only place a node reaches a provider, so every call lands in the ledger."""
    response = await deps.provider.complete(request)
    await deps.ledger.record(
        tenant_id=turn.tenant_id,
        turn_id=turn.turn_id,
        node=node,
        provider=deps.provider.name,
        response=response,
    )
    return response


async def _classify(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    try:
        return await _classification(state, runtime.context)
    except ModelFilteredError:
        # The provider would not let a model read the message, which is what it does with
        # a jailbreak attempt. Nothing in it is acted on: it gets the fixed refusal.
        return {"in_scope": False, "model_calls": 1}


async def _classification(state: _State, deps: AgentDeps) -> _State:
    response = await _call_model(
        deps,
        state["turn"],
        "classify",
        ModelRequest(
            model=_model(deps, state, "classify"),
            system=prompts.classify_prompt(state["tenant_name"]),
            messages=tuple(state["transcript"]),
            output_schema=Classification.model_json_schema(),
            # Reasoning tokens count against this limit, so it is far above the answer.
            max_output_tokens=512,
            reasoning_effort="low",
            timeout_s=20,
        ),
    )
    classification = Classification.model_validate_json(response.text or "")
    update: _State = {"in_scope": classification.in_scope, **_spent(response)}
    if classification.wants_human:
        update["handoff_reason"] = "customer_asked"
    return update


async def _retrieve(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    """Finds what the tenant's knowledge base has about the message, for the planner.

    Retrieval is an aid. When the embedding model cannot be reached the turn goes on
    without it, on the tools and the opening hours alone.
    """
    deps, turn = runtime.context, state["turn"]
    if deps.embedder is None:
        return {"knowledge": ""}
    try:
        embedded = await deps.embedder.embed(["\n".join(turn.messages)])
    except ModelError:
        return {"knowledge": ""}
    await deps.ledger.record_usage(
        tenant_id=turn.tenant_id,
        turn_id=turn.turn_id,
        node="retrieve",
        provider=deps.embedder.name,
        model=deps.embedder.model,
        usage=embedded.usage,
        latency_ms=embedded.latency_ms,
    )
    async with tenant_transaction(deps.sessions, turn.tenant_id) as session:
        chunks = await knowledge.search(
            session,
            embedded.vectors[0],
            deps.embedder.model,
            max_distance=deps.embedder.max_distance,
        )
    if not chunks:
        return {"knowledge": ""}
    found = "\n".join(f"- {chunk.title}: {chunk.body}" for chunk in chunks)
    return {
        "knowledge": found,
        "plan_system": state["plan_system"] + prompts.knowledge_block(found),
        "facts": facts_in(found, "knowledge", today=state["today"]),
    }


async def _handoff(state: _State) -> _State:  # noqa: ARG001  a node is called with the state
    return {"outcome": "handoff", "reply": prompts.HANDOFF_NOTICE}


async def _refuse(state: _State) -> _State:
    return {"outcome": "refused", "reply": prompts.REFUSAL.format(tenant=state["tenant_name"])}


async def _plan(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    deps = runtime.context
    request = ModelRequest(
        model=_model(deps, state, "plan"),
        system=state["plan_system"],
        messages=tuple(state["transcript"]),
        tools=TOOL_SPECS,
        max_output_tokens=2048,
        reasoning_effort="low",
        timeout_s=45,
    )
    try:
        response = await _call_model(deps, state["turn"], "plan", request)
    except ModelFilteredError:
        return {**(await _refuse(state)), "model_calls": 1}
    if response.stop_reason == "filtered":
        return {**(await _refuse(state)), **_spent(response)}
    said = Message(role="assistant", content=response.text or "", tool_calls=response.tool_calls)
    if response.tool_calls:
        return {"transcript": [said], **_spent(response)}
    return {"transcript": [said], "draft": said.content, **_spent(response)}


async def _validate(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    """Sends the draft, or sends it back once with what is wrong, or gives the turn up."""
    draft = state["draft"]
    problems = review(
        draft,
        state.get("facts", []),
        state.get("effects", []),
        today=state["today"],
        knowledge=state.get("knowledge", ""),
    )
    if not problems:
        return {"outcome": "replied", "reply": draft}
    if state.get("blocks", 0) >= 1:
        return {"blocks": 1, "handoff_reason": "guardrail_blocked"}
    if _spent_up(runtime.context.limits, state):
        return {"blocks": 1, "handoff_reason": "turn_limit"}
    return {
        "blocks": 1,
        "transcript": [Message(role="user", content=prompts.correction(problems))],
    }


async def _gate(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    """Decides whether what the planner asked for may run now, has to wait, or may not."""
    turn = state["turn"]
    calls = state["transcript"][-1].tool_calls
    async with tenant_transaction(runtime.context.sessions, turn.tenant_id) as session:
        tenant = await load_tenant(session, turn.tenant_id)
        for call in calls:
            rule = await approvals.sensitive_rule(
                session, tenant, turn.customer_id, call.name, call.arguments, turn.now
            )
            if rule is None:
                continue
            if await approvals.has_pending(session, turn.conversation_id):
                return _denied(runtime.context.limits, state, "approval_already_pending")
            waiting = {"rule": rule, "tool": call.name, "arguments": call.arguments}
            # The rule only fires for a confirmed booking of this customer, so the turn
            # knows the booking exists, which a reply may say whatever the owner decides.
            return {"gate": "wait", "approval": waiting, "effects": ["listed"]}
    return {"gate": "allow"}


async def _await_approval(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    # Alone in its node on purpose: when the graph resumes, the node that called the
    # interrupt runs again from its first line, so nothing else may live here.
    approved = interrupt(state["approval"])
    if approved:
        return {"gate": "allow"}
    return _denied(runtime.context.limits, state, "rejected_by_owner")


def _denied(limits: TurnLimits, state: _State, reason: str) -> _State:
    """Answers every call of the batch with the refusal, for the planner to explain."""
    refusals = [
        Message(role="tool", tool_call_id=call.id, content=json.dumps({"error": reason}))
        for call in state["transcript"][-1].tool_calls
    ]
    update: _State = {"gate": "deny", "transcript": refusals}
    if _spent_up(limits, state):
        update["handoff_reason"] = "turn_limit"
    return update


async def _execute(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    transcript = state["transcript"]
    asked = next(message for message in reversed(transcript) if message.tool_calls)
    already_run = sum(1 for message in transcript if message.role == "tool")
    timezone = ZoneInfo(state["timezone"])
    outcomes = [
        await run_tool_call(
            runtime.context.sessions, state["turn"], call, already_run + index, timezone
        )
        for index, call in enumerate(asked.tool_calls)
    ]
    update: _State = {
        "transcript": [outcome.message for outcome in outcomes],
        "facts": [Sourced(fact, "tool") for outcome in outcomes for fact in outcome.facts],
        "effects": [outcome.effect for outcome in outcomes if outcome.effect],
        "tool_rounds": 1,
    }
    if _over(runtime.context.limits, state):
        update["handoff_reason"] = "turn_limit"
    return update


def _spent(response: ModelResponse) -> _State:
    usage = response.usage
    return {"model_calls": 1, "tokens": usage.input_tokens + usage.output_tokens}


def _over(limits: TurnLimits, state: _State) -> bool:
    """Whether another plan call would pass a limit, counting the round that just ran."""
    return state.get("tool_rounds", 0) + 1 >= limits.tool_rounds or _spent_up(limits, state)


def _spent_up(limits: TurnLimits, state: _State) -> bool:
    return (
        state.get("model_calls", 0) >= limits.model_calls or state.get("tokens", 0) >= limits.tokens
    )


def _said_by_the_customer(turn: TurnInput, today: dt.date) -> list[Sourced]:
    """Values the customer wrote, now or earlier, which the agent may repeat back.

    A price among them does not become a price the agent may state: the guardrail accepts
    money from tools only.
    """
    texts = [*turn.messages, *(past.text for past in turn.history if past.author == "customer")]
    return [fact for text in texts for fact in facts_in(text, "customer", today=today)]


def _after_context(state: _State) -> Literal["classify", "handoff"]:
    return "handoff" if "handoff_reason" in state else "classify"


def _after_classify(state: _State) -> Literal["retrieve", "refuse", "handoff"]:
    if "handoff_reason" in state:
        return "handoff"
    return "retrieve" if state["in_scope"] else "refuse"


def _after_execute(state: _State) -> Literal["plan", "handoff"]:
    return "handoff" if "handoff_reason" in state else "plan"


def _after_plan(state: _State) -> Literal["gate", "validate", "done"]:
    if "outcome" in state:
        return "done"
    return "gate" if state["transcript"][-1].tool_calls else "validate"


def _after_gate(state: _State) -> Literal["execute", "await_approval", "plan", "handoff"]:
    if "handoff_reason" in state:
        return "handoff"
    return {"allow": "execute", "wait": "await_approval", "deny": "plan"}[state["gate"]]  # type: ignore[return-value]


def _after_validate(state: _State) -> Literal["done", "plan", "handoff"]:
    if "outcome" in state:
        return "done"
    return "handoff" if "handoff_reason" in state else "plan"


def _history(turn: TurnInput) -> list[Message]:
    roles: dict[str, Literal["user", "assistant"]] = {"customer": "user", "agent": "assistant"}
    return [Message(role=roles[past.author], content=past.text) for past in turn.history]


type _Node = Callable[..., Awaitable[_State]]


class _TimedNode(Protocol):
    async def __call__(self, state: _State, *, runtime: Runtime[AgentDeps]) -> _State: ...


def _timed(name: str, node: _Node) -> _TimedNode:
    """Wraps a node so that the turn records it as a step of its timeline."""
    wants_runtime = len(inspect.signature(node).parameters) > 1

    async def timed(state: _State, *, runtime: Runtime[AgentDeps]) -> _State:
        started = time.perf_counter()
        # An interrupt leaves through here as an exception and records nothing: the node
        # runs again when the turn resumes, and that run is the one that counts.
        update = await (node(state, runtime) if wants_runtime else node(state))
        step = {
            "node": name,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "detail": _detail(name, state, update),
        }
        return {**update, "steps": [step]}

    return timed


def _detail(name: str, state: _State, update: _State) -> dict[str, Any]:
    """What a step of the timeline says about itself. Names and outcomes, never text."""
    if name == "classify":
        return {"in_scope": update.get("in_scope"), "wants_human": "handoff_reason" in update}
    if name == "plan":
        said = update.get("transcript", [])
        calls = [call.name for message in said for call in message.tool_calls]
        return {"tools": calls} if calls else {"wrote_reply": "draft" in update}
    if name in ("gate", "await_approval"):
        return {"decision": update.get("gate")}
    if name == "execute":
        return {"effects": update.get("effects", []), "results": len(update.get("transcript", []))}
    if name == "validate":
        return {"passed": "outcome" in update}
    if name == "retrieve":
        return {"chunks": len(update.get("knowledge", "").splitlines())}
    if name == "handoff":
        return {"reason": state.get("handoff_reason")}
    return {}


def _build() -> StateGraph[_State, AgentDeps]:
    graph = StateGraph(_State, context_schema=AgentDeps)
    nodes: dict[str, _Node] = {
        "load_context": _load_context,
        "classify": _classify,
        "refuse": _refuse,
        "handoff": _handoff,
        "retrieve": _retrieve,
        "plan": _plan,
        "gate": _gate,
        "await_approval": _await_approval,
        "execute": _execute,
        "validate": _validate,
    }
    for name, node in nodes.items():
        graph.add_node(name, _timed(name, node))
    graph.add_edge(START, "load_context")
    graph.add_conditional_edges("load_context", _after_context)
    graph.add_conditional_edges("classify", _after_classify)
    graph.add_edge("retrieve", "plan")
    graph.add_edge("refuse", END)
    graph.add_edge("handoff", END)
    graph.add_conditional_edges(
        "plan", _after_plan, {"gate": "gate", "validate": "validate", "done": END}
    )
    graph.add_conditional_edges("gate", _after_gate)
    graph.add_conditional_edges("await_approval", _after_gate)
    graph.add_conditional_edges("execute", _after_execute)
    graph.add_conditional_edges(
        "validate", _after_validate, {"done": END, "plan": "plan", "handoff": "handoff"}
    )
    return graph


@lru_cache(maxsize=16)
def _compiled(checkpointer: BaseCheckpointSaver[str]) -> CompiledStateGraph[_State, AgentDeps]:
    return _build().compile(checkpointer=checkpointer)
