import asyncio
from typing import Any

from .llm import AgentDependencyError, GeminiClient
from .prompts import executor_prompt, planner_prompt
from .state import AgentState, BrowserObservation
from .tools import agent_browser


_COMPILED_GRAPH: Any | None = None
_OBSERVATION_COMMANDS = (
    "snapshot",
    "get ",
    "is ",
    "find ",
    "eval ",
    "screenshot",
    "console",
    "errors",
)


def _require_langgraph() -> tuple[Any, Any, Any]:
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, StateGraph
    except ModuleNotFoundError as exc:
        raise AgentDependencyError(
            "Missing langgraph. Run `uv sync` or `uv add langgraph`."
        ) from exc
    return StateGraph, END, MemorySaver


def _default_validation_command(command: str) -> str:
    normalized = command.strip().lower()
    if not normalized:
        return ""
    if normalized.startswith(_OBSERVATION_COMMANDS):
        return ""
    if normalized.startswith("open ") or normalized in {"back", "forward", "reload"}:
        return "snapshot -i -c"
    if normalized.startswith(("click ", "dblclick ", "press ", "keyboard ")):
        return "snapshot -i -c"
    if normalized.startswith(("fill ", "type ", "check ", "uncheck ", "select ")):
        return "snapshot -i -c"
    if normalized.startswith(("scroll", "wait ", "hover ", "focus ", "tab ")):
        return "snapshot -i -c"
    return "snapshot -i -c"


async def _planner_node(state: AgentState) -> AgentState:
    if state.get("step_count", 0) >= state.get("max_steps", 40):
        return {
            "planner_status": "failed",
            "planner_reason": "Maximum agent loop steps reached.",
            "final": "I stopped because the task hit the maximum step limit.",
            "task_status": "failed",
        }

    client = GeminiClient()
    decision = await client.generate_json(planner_prompt(state))
    status = str(decision.get("status", "continue")).strip().lower()
    if status not in {"continue", "done", "need_user", "failed"}:
        status = "continue"
    question = str(decision.get("question", "")).strip()
    choices = [str(item) for item in decision.get("choices", [])]
    task_status = "waiting_for_user" if status == "need_user" else status
    return {
        "planner_status": status,
        "planner_reason": str(decision.get("reason", "")),
        "plan": [str(item) for item in decision.get("plan", state.get("plan", []))],
        "next_task": str(decision.get("next_task", "")),
        "final": str(decision.get("final", "")),
        "pending_question": question,
        "pending_choices": choices,
        "task_status": task_status,
        "user_feedback": "",
    }


async def _executor_node(state: AgentState) -> AgentState:
    if state.get("step_count", 0) >= state.get("max_steps", 40):
        return {
            "executor_status": "blocked",
            "executor_reason": "Maximum browser command steps reached.",
            "executor_thought": "The task needs planner review because the step limit was reached.",
            "browser_command": "",
            "success_criteria": "",
        }

    client = GeminiClient()
    selected = await client.generate_json(executor_prompt(state))
    status = str(selected.get("status", "continue")).strip().lower()
    if status not in {"continue", "done", "blocked"}:
        status = "continue"

    has_command = "command" in selected
    command = str(selected.get("command", "")).strip()
    success_criteria = str(selected.get("success_criteria", "")).strip()
    validation_command = str(selected.get("validation_command", "")).strip()
    thought = str(selected.get("thought", "")).strip()
    result_summary = str(selected.get("result_summary", "")).strip()

    if status != "continue" or not has_command:
        return {
            "executor_status": status if has_command else "blocked",
            "executor_reason": result_summary or "Executor is handing control back to the planner.",
            "executor_thought": thought,
            "browser_command": "",
            "validation_command": "",
            "success_criteria": success_criteria,
        }

    result = await asyncio.to_thread(agent_browser, command)
    ok = result.get("status") == "success"
    output = result.get("data") or result.get("message") or result.get("logs") or ""
    error = result.get("error") or result.get("reason") or ""

    if ok and not validation_command:
        validation_command = _default_validation_command(command)

    validation_ok = False
    validation_output = ""
    validation_error = ""
    if ok and validation_command:
        validation_result = await asyncio.to_thread(agent_browser, validation_command)
        validation_ok = validation_result.get("status") == "success"
        validation_output = (
            validation_result.get("data")
            or validation_result.get("message")
            or validation_result.get("logs")
            or ""
        )
        validation_error = str(
            validation_result.get("error") or validation_result.get("reason") or ""
        )

    observation: BrowserObservation = {
        "command": command,
        "ok": bool(ok),
        "output": output,
        "error": str(error),
        "success_criteria": success_criteria,
        "validation_command": validation_command,
        "validation_ok": validation_ok,
        "validation_output": validation_output,
        "validation_error": validation_error,
    }

    return {
        "executor_status": "continue",
        "executor_reason": result_summary,
        "executor_thought": thought,
        "browser_command": command,
        "validation_command": validation_command,
        "success_criteria": success_criteria,
        "observations": [*state.get("observations", []), observation],
        "step_count": state.get("step_count", 0) + 1,
    }


def _route_after_planner(state: AgentState) -> str:
    if state.get("planner_status") == "continue" and state.get("next_task"):
        return "execute"
    return "finish"


def _route_after_executor(state: AgentState) -> str:
    if (
        state.get("executor_status") == "continue"
        and state.get("step_count", 0) < state.get("max_steps", 40)
    ):
        return "execute"
    return "plan"


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
    graph.add_conditional_edges(
        "executor",
        _route_after_executor,
        {"execute": "executor", "plan": "planner"},
    )
    _COMPILED_GRAPH = graph.compile(checkpointer=MemorySaver())
    return _COMPILED_GRAPH
