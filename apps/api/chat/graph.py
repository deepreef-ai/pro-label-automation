"""LangGraph agent: router -> tool calls -> answer, over ``core.llm`` with a JSON protocol.

Free models do not all support native tool calling, so every turn the model replies with
ONE JSON object: ``{"tool": "<name>", "args": {...}}`` to call a tool, or
``{"answer": "...", "actions": [{"type": "navigate", "to": "/..."}]}`` to finish. At most
``MAX_STEPS`` tool calls; unknown tools are refused and reported back to the model.

Safety: only tools from ``chat.tools.TOOLS`` run (read or draft, never write). Draft
actions come only from draft-tool results, never from model text; model-proposed actions
are reduced to ``navigate`` with a known route by ``chat.service``.

``run_agent`` raises ``LLMUnavailable`` when no provider answers and ``AgentGaveUp`` when the
model never produced a usable answer; ``chat.service`` then answers deterministically.
"""
from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from chat.tools import TOOLS, ToolContext, describe_tools
from core.llm.gateway import LLMUnavailable, extract_json

log = logging.getLogger(__name__)

MAX_STEPS = 3
RESULT_CHARS = 3500


class AgentGaveUp(Exception):
    """The model did not produce a usable answer within the step budget."""


SYSTEM = """You are the AI assistant inside Pro Labels' operations app (a label-printing plant).
Screens (routes): / dashboard, /marketing, /jobs, /jobs/JC-####, /design, /store, /production, /qc,
/dispatch, /money (debtors, invoices, collections, creditors, cash plan, P&L), /agents, /floor, /settings.
The user's role is "{role}".

Tools (read tools fetch live data; draft tools only PREPARE a change that the user confirms in the UI):
{tools}

Protocol. Reply with ONE JSON object and nothing else:
- to call a tool: {{"tool": "<tool name>", "args": {{...}}}}
- to finish: {{"answer": "<reply to the user>", "actions": [{{"type": "navigate", "to": "/route"}}]}}
Rules:
- Use tools to get facts; never invent numbers. Never calculate money, stock or percentages
  yourself: quote the figures the tools return.
- You cannot change data. For changes use a draft tool; say the user must press Confirm.
- Only the owner may release a client lock.
- Answer in the user's language: if they write Hindi or Hinglish, answer in Hindi (Devanagari).
- Keep answers short (2-6 sentences or a short list). Amounts in Indian format (Rs 12,34,567).
"""


class AgentState(TypedDict, total=False):
    messages: list
    steps: int
    answer: str | None
    llm_actions: list
    drafts: list
    sources: list
    tools_used: list
    done: bool


def _parse(text: str) -> dict:
    try:
        data = extract_json(text)
    except Exception:
        data = None
    if isinstance(data, dict):
        return data
    return {"answer": text.strip()} if text and text.strip() else {}


def _dump(result: Any) -> str:
    text = json.dumps(result, ensure_ascii=False, default=str)
    return text if len(text) <= RESULT_CHARS else text[:RESULT_CHARS] + "...(truncated)"


def _initial(message: str, role: str, history: list | None) -> AgentState:
    msgs = [{"role": "system", "content": SYSTEM.format(role=role, tools=describe_tools())}]
    for h in (history or [])[-6:]:
        if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:1500]})
    msgs.append({"role": "user", "content": message})
    return {"messages": msgs, "steps": 0, "answer": None, "llm_actions": [], "drafts": [],
            "sources": [], "tools_used": [], "done": False}


def _agent_step(state: AgentState, gateway: Any, ctx: ToolContext) -> AgentState:
    """One model turn (+ the tool it asks for). Returns the updated state."""
    msgs = list(state["messages"])
    if state["steps"] >= MAX_STEPS:
        msgs.append({"role": "user", "content": 'No more tools. Reply now with {"answer": "..."} only.'})
    res = gateway.complete(msgs, purpose="chat")  # may raise LLMUnavailable
    data = _parse(res.text)
    msgs.append({"role": "assistant", "content": res.text})
    tool_name = data.get("tool")
    answer = data.get("answer")
    if answer is None and isinstance(data.get("reply"), str) and not tool_name:
        answer = data["reply"]

    if tool_name and state["steps"] < MAX_STEPS:
        steps = state["steps"] + 1
        tool = TOOLS.get(str(tool_name))
        if tool is None:
            msgs.append({"role": "user", "content": f"TOOL_ERROR: unknown tool {tool_name!r}. "
                         f"Available: {', '.join(TOOLS)}. You cannot change data directly."})
            return {**state, "messages": msgs, "steps": steps}
        args = data.get("args") if isinstance(data.get("args"), dict) else {}
        try:
            result = tool.run(args, ctx)
        except Exception as exc:
            result = {"error": str(exc)}
        drafts, sources = list(state["drafts"]), list(state["sources"])
        if tool.mode == "draft" and isinstance(result, dict) and result.get("type") == "draft":
            drafts.append(result)
        if isinstance(result, dict):
            sources += [s for s in result.get("sources", []) if isinstance(s, dict)]
        msgs.append({"role": "user", "content": f"TOOL_RESULT {tool.name}: {_dump(result)}"})
        return {**state, "messages": msgs, "steps": steps, "drafts": drafts, "sources": sources,
                "tools_used": state["tools_used"] + [tool.name]}

    if isinstance(answer, str) and answer.strip():
        actions = data.get("actions") if isinstance(data.get("actions"), list) else []
        return {**state, "messages": msgs, "answer": answer.strip(), "llm_actions": actions, "done": True}
    if state["steps"] >= MAX_STEPS:
        raise AgentGaveUp("no answer within step budget")
    return {**state, "messages": msgs, "steps": state["steps"] + 1}


def _build_graph(gateway: Any, ctx: ToolContext):
    from langgraph.graph import END, StateGraph

    def agent(state: AgentState) -> AgentState:
        return _agent_step(state, gateway, ctx)

    def route(state: AgentState) -> str:
        return "end" if state.get("done") else "agent"

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", route, {"agent": "agent", "end": END})
    return g.compile()


def run_agent(message: str, *, role: str, gateway: Any, ctx: ToolContext,
              history: list | None = None) -> AgentState:
    state = _initial(message, role, history)
    try:
        graph = _build_graph(gateway, ctx)
    except ImportError:  # langgraph missing: same loop, plain Python
        graph = None
    if graph is not None:
        out = graph.invoke(state, {"recursion_limit": 2 * MAX_STEPS + 4})
    else:
        out = state
        for _ in range(MAX_STEPS + 2):
            out = _agent_step(out, gateway, ctx)
            if out.get("done"):
                break
    if not out.get("done"):
        raise AgentGaveUp("agent did not finish")
    return out


__all__ = ["run_agent", "AgentGaveUp", "LLMUnavailable", "MAX_STEPS"]
