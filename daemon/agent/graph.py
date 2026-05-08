import asyncio
from typing import Any

from .llm import AgentDependencyError, GeminiClient
from .prompts import executor_prompt, planner_prompt
from .state import AgentState, BrowserObservation
from .tools import agent_browser


_COMPILED_GRAPH: Any | None = None


def _require_langgraph() -> tuple[Any, Any, Any]:
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, StateGraph
    except ModuleNotFoundError as exc:
        raise AgentDependencyError(
            "Missing langgraph. Run `uv sync` or `uv add langgraph`."
        ) from exc
    return StateGraph, END, MemorySaver


async def _planner_node(state: AgentState) -> AgentState:
    if state.get("step_count", 0) >= state.get("max_steps", 20):
        return {
            "planner_status": "failed",
            "planner_reason": "Maximum agent loop steps reached.",
            "final": "I stopped because the task hit the maximum step limit.",
        }

    client = GeminiClient()
    decision = await client.generate_json(planner_prompt(state))
    status = str(decision.get("status", "continue"))
    return {
        "planner_status": status,
        "planner_reason": str(decision.get("reason", "")),
        "plan": [str(item) for item in decision.get("plan", state.get("plan", []))],
        "next_task": str(decision.get("next_task", "")),
        "final": str(decision.get("final", "")),
    }


async def _executor_node(state: AgentState) -> AgentState:
    client = GeminiClient()
    selected = await client.generate_json(executor_prompt(state))
    command = str(selected.get("command", "")).strip()
    success_criteria = str(selected.get("success_criteria", "")).strip()

    result = await asyncio.to_thread(agent_browser, command)
    ok = result.get("status") == "success"
    output = result.get("data") or result.get("message") or result.get("logs") or ""
    error = result.get("error") or result.get("reason") or ""
    observation: BrowserObservation = {
        "command": command,
        "ok": bool(ok),
        "output": output,
        "error": str(error),
        "success_criteria": success_criteria,
    }

    return {
        "executor_thought": str(selected.get("thought", "")),
        "browser_command": command,
        "success_criteria": success_criteria,
        "observations": [*state.get("observations", []), observation],
        "step_count": state.get("step_count", 0) + 1,
    }


def _route_after_planner(state: AgentState) -> str:
    if state.get("planner_status") == "continue" and state.get("next_task"):
        return "execute"
    return "finish"


def build_graph() -> Any:
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is not None:
        return _COMPILED_GRAPH

    StateGraph, END, MemorySaver = _require_langgraph()

    graph = StateGraph(AgentState)
    graph.add_node("planner", _planner_node)
    graph.add_node("executor", _executor_node)
    graph.set_entry_point("planner")
    graph.add_conditional_edges(
        "planner",
        _route_after_planner,
        {"execute": "executor", "finish": END},
    )
    graph.add_edge("executor", "planner")
    _COMPILED_GRAPH = graph.compile(checkpointer=MemorySaver())
    return _COMPILED_GRAPH
