"""The turn as an explicit graph (docs/design/agent-graph.md).

    load_context -> classify -> plan <-> execute
               \\           \\-> refuse
                \\-> handoff <-/

The planner's last message, the one without tool calls, is the reply. Persisting it and
sending it belong to the worker, so the graph knows nothing about channels.
"""

import operator
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, ConfigDict

from frontdesk.agent import intents, prompts
from frontdesk.agent.tool_runner import run_tool_call
from frontdesk.agent.turn import HandoffReason, HistoryMessage, TurnInput, TurnResult
from frontdesk.db.session import SessionFactory, tenant_transaction
from frontdesk.domain.clock import to_local
from frontdesk.domain.tenants import load_tenant, timezone_of
from frontdesk.providers.ledger import ModelLedger
from frontdesk.providers.port import Message, ModelProvider, ModelRequest, ModelResponse
from frontdesk.tools.registry import TOOL_SPECS

__all__ = ["AgentDeps", "HistoryMessage", "TurnInput", "TurnResult", "run_turn"]

# Above anything a healthy turn reaches. Phase 2 replaces the exception this raises
# with counted limits that end in handoff.
_RECURSION_LIMIT = 25


@dataclass(frozen=True)
class AgentDeps:
    sessions: SessionFactory
    provider: ModelProvider
    model: str
    ledger: ModelLedger


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
    outcome: Literal["replied", "refused", "handoff"]
    reply: str


async def run_turn(deps: AgentDeps, turn: TurnInput) -> TurnResult:
    final = await _GRAPH.ainvoke(
        {"turn": turn, "transcript": []},
        config={"recursion_limit": _RECURSION_LIMIT},
        context=deps,
    )
    return TurnResult(
        outcome=final["outcome"],
        reply=final["reply"],
        handoff_reason=final.get("handoff_reason") if final["outcome"] == "handoff" else None,
    )


async def _load_context(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    turn = state["turn"]
    async with tenant_transaction(runtime.context.sessions, turn.tenant_id) as session:
        tenant = await load_tenant(session, turn.tenant_id)
    local_now = to_local(turn.now, timezone_of(tenant))
    context: _State = {
        "tenant_name": tenant.name,
        "plan_system": prompts.plan_prompt(tenant.name, local_now),
        "transcript": [*_history(turn), Message(role="user", content="\n".join(turn.messages))],
    }
    # Decided here, by matching, so that no wording in the rest of the message and no
    # answer of a model can keep a customer from reaching a person.
    if intents.asks_for_a_person(turn.messages):
        context["handoff_reason"] = "customer_asked"
    return context


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
    deps = runtime.context
    response = await _call_model(
        deps,
        state["turn"],
        "classify",
        ModelRequest(
            model=deps.model,
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
    if classification.wants_human:
        return {"in_scope": classification.in_scope, "handoff_reason": "customer_asked"}
    return {"in_scope": classification.in_scope}


async def _handoff(state: _State) -> _State:  # noqa: ARG001  a node is called with the state
    return {"outcome": "handoff", "reply": prompts.HANDOFF_NOTICE}


async def _refuse(state: _State) -> _State:
    return {"outcome": "refused", "reply": prompts.REFUSAL.format(tenant=state["tenant_name"])}


async def _plan(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    deps = runtime.context
    response = await _call_model(
        deps,
        state["turn"],
        "plan",
        ModelRequest(
            model=deps.model,
            system=state["plan_system"],
            messages=tuple(state["transcript"]),
            tools=TOOL_SPECS,
            max_output_tokens=2048,
            reasoning_effort="low",
            timeout_s=45,
        ),
    )
    said = Message(role="assistant", content=response.text or "", tool_calls=response.tool_calls)
    if response.tool_calls:
        return {"transcript": [said]}
    return {"transcript": [said], "outcome": "replied", "reply": said.content}


async def _execute(state: _State, runtime: Runtime[AgentDeps]) -> _State:
    transcript = state["transcript"]
    already_run = sum(1 for message in transcript if message.role == "tool")
    results = [
        await run_tool_call(runtime.context.sessions, state["turn"], call, already_run + index)
        for index, call in enumerate(transcript[-1].tool_calls)
    ]
    return {"transcript": results}


def _after_context(state: _State) -> Literal["classify", "handoff"]:
    return "handoff" if "handoff_reason" in state else "classify"


def _after_classify(state: _State) -> Literal["plan", "refuse", "handoff"]:
    if "handoff_reason" in state:
        return "handoff"
    return "plan" if state["in_scope"] else "refuse"


def _after_plan(state: _State) -> Literal["execute", "done"]:
    return "execute" if state["transcript"][-1].tool_calls else "done"


def _history(turn: TurnInput) -> list[Message]:
    roles: dict[str, Literal["user", "assistant"]] = {"customer": "user", "agent": "assistant"}
    return [Message(role=roles[past.author], content=past.text) for past in turn.history]


def _build() -> StateGraph[_State, AgentDeps]:
    graph = StateGraph(_State, context_schema=AgentDeps)
    graph.add_node("load_context", _load_context)
    graph.add_node("classify", _classify)
    graph.add_node("refuse", _refuse)
    graph.add_node("handoff", _handoff)
    graph.add_node("plan", _plan)
    graph.add_node("execute", _execute)
    graph.add_edge(START, "load_context")
    graph.add_conditional_edges("load_context", _after_context)
    graph.add_conditional_edges("classify", _after_classify)
    graph.add_edge("refuse", END)
    graph.add_edge("handoff", END)
    graph.add_conditional_edges("plan", _after_plan, {"execute": "execute", "done": END})
    graph.add_edge("execute", "plan")
    return graph


_GRAPH = _build().compile()
