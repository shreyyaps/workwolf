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
_SIDE_EFFECT_WORDS = (
    "send",
    "sent",
    "submit",
    "submitted",
    "post",
    "posted",
    "publish",
    "published",
    "purchase",
    "purchased",
    "pay",
    "paid",
    "order",
    "ordered",
    "book",
    "booked",
    "delete",
    "deleted",
    "remove",
    "removed",
    "confirm",
    "confirmed",
    "invite",
    "invited",
)
_STATE_CHANGING_COMMANDS = (
    "click ",
    "dblclick ",
    "press ",
    "keyboard ",
    "fill ",
    "type ",
    "check ",
    "uncheck ",
    "select ",
    "drag ",
    "upload ",
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
    return "snapshot -i -c"


def _is_state_changing_command(command: str) -> bool:
    normalized = command.strip().lower()
    return normalized.startswith(_STATE_CHANGING_COMMANDS) or normalized in {
        "back",
        "forward",
        "reload",
    } or normalized.startswith(("open ", "tab ", "scroll"))


def _looks_like_side_effect(state: AgentState, command: str, criteria: str) -> bool:
    if not _is_state_changing_command(command):
        return False
    normalized = command.strip().lower()
    direct_context = f"{command} {criteria}".lower()
    if any(word in direct_context for word in _SIDE_EFFECT_WORDS):
        return True

    if normalized.startswith(("click ", "press ", "keyboard ")):
        task_context = f"{state.get('user_prompt', '')} {state.get('next_task', '')}".lower()
        return any(word in task_context for word in _SIDE_EFFECT_WORDS)

    return False


def _already_attempted_side_effect(state: AgentState) -> bool:
    return any(
        bool(observation.get("side_effect")) and bool(observation.get("ok"))
        for observation in state.get("observations", [])
    )


def _validation_commands_from_selected(selected: dict[str, Any]) -> list[str]:
    raw_commands = selected.get("validation_commands")
    if isinstance(raw_commands, list):
        return [str(item).strip() for item in raw_commands if str(item).strip()]

    command = str(selected.get("validation_command", "")).strip()
    return [command] if command else []


def _default_validation_commands(
    state: AgentState,
    command: str,
    criteria: str,
    side_effect: bool,
) -> list[str]:
    default = _default_validation_command(command)
    if not default:
        return []

    if side_effect:
        context = " ".join(
            [
                str(state.get("user_prompt", "")),
                str(state.get("next_task", "")),
                criteria,
            ]
        ).lower()
        commands = ["wait 1200"]
        if any(word in context for word in ("gmail", "email", "mail", "message")):
            commands.append(
                "eval \"(() => { const text = document.body.innerText; "
                "const matches = text.match(/Message sent|Undo|View message|"
                "Sending|Draft saved|New Message/gi); "
                "return matches ? matches.join(' | ') : text.slice(-2000); })()\""
            )
        commands.extend(
            [
                "snapshot -i -c",
                "snapshot -i -c -d 5",
                "screenshot --annotate /tmp/wolfie-validation.png",
            ]
        )
        return commands

    return [default]


async def _run_validation_commands(commands: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for command in commands:
        result = await asyncio.to_thread(agent_browser, command)
        results.append(
            {
                "command": command,
                "ok": result.get("status") == "success",
                "output": result.get("data")
                or result.get("message")
                or result.get("logs")
                or "",
                "error": str(result.get("error") or result.get("reason") or ""),
            }
        )
    return results


def _validation_output(results: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for result in results:
        status = "ok" if result.get("ok") else "failed"
        output = result.get("output") or result.get("error") or ""
        chunks.append(f"$ agent-browser {result.get('command', '')}\n[{status}]\n{output}")
    return "\n\n".join(chunks)


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
    validation_commands = _validation_commands_from_selected(selected)
    thought = str(selected.get("thought", "")).strip()
    result_summary = str(selected.get("result_summary", "")).strip()

    if status != "continue" or not has_command:
        return {
            "executor_status": status if has_command else "blocked",
            "executor_reason": result_summary or "Executor is handing control back to the planner.",
            "executor_thought": thought,
            "browser_command": "",
            "validation_command": "",
            "validation_commands": [],
            "success_criteria": success_criteria,
        }

    side_effect = _looks_like_side_effect(state, command, success_criteria)
    duplicate_side_effect = side_effect and _already_attempted_side_effect(state)
    if duplicate_side_effect:
        if not validation_commands:
            validation_commands = _default_validation_commands(
                state,
                command,
                success_criteria,
                side_effect=True,
            )
        validation_results = await _run_validation_commands(validation_commands)
        validation_output = _validation_output(validation_results)
        observation: BrowserObservation = {
            "command": command,
            "skipped": True,
            "side_effect": True,
            "ok": False,
            "output": "",
            "error": (
                "Skipped a likely duplicate side-effect action. "
                "Validate with read-only commands or ask the user before retrying."
            ),
            "success_criteria": success_criteria,
            "validation_command": " && ".join(validation_commands),
            "validation_commands": validation_commands,
            "validation_ok": all(result.get("ok") for result in validation_results),
            "validation_output": validation_output,
            "validation_error": "",
            "validation_results": validation_results,
        }
        return {
            "executor_status": "continue",
            "executor_reason": "Skipped likely duplicate side-effect action.",
            "executor_thought": thought,
            "browser_command": command,
            "validation_command": " && ".join(validation_commands),
            "validation_commands": validation_commands,
            "success_criteria": success_criteria,
            "observations": [*state.get("observations", []), observation],
            "step_count": state.get("step_count", 0) + 1,
        }

    result = await asyncio.to_thread(agent_browser, command)
    ok = result.get("status") == "success"
    output = result.get("data") or result.get("message") or result.get("logs") or ""
    error = result.get("error") or result.get("reason") or ""

    if ok and not validation_commands:
        validation_commands = _default_validation_commands(
            state,
            command,
            success_criteria,
            side_effect,
        )

    validation_results = (
        await _run_validation_commands(validation_commands)
        if ok and validation_commands
        else []
    )
    validation_output = _validation_output(validation_results)
    observation: BrowserObservation = {
        "command": command,
        "side_effect": side_effect,
        "ok": bool(ok),
        "output": output,
        "error": str(error),
        "success_criteria": success_criteria,
        "validation_command": " && ".join(validation_commands),
        "validation_commands": validation_commands,
        "validation_ok": all(result.get("ok") for result in validation_results)
        if validation_results
        else False,
        "validation_output": validation_output,
        "validation_error": "",
        "validation_results": validation_results,
    }

    return {
        "executor_status": "continue",
        "executor_reason": result_summary,
        "executor_thought": thought,
        "browser_command": command,
        "validation_command": " && ".join(validation_commands),
        "validation_commands": validation_commands,
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
