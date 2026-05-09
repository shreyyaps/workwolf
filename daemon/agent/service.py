import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

from llm_orchestration_langgraph.functions.agent_browser_vercel import USER_DATA_DIR

from .events import event
from .graph import build_graph
from .llm import AgentDependencyError, reset_request_api_key, set_request_api_key
from .state import initial_state
from .tools import agent_browser


def _clean_text(value: Any, limit: int = 8000) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + "\n...[middle truncated]...\n" + text[-half:]


def _events_from_update(update: dict[str, Any]) -> list[dict[str, Any]]:
    emitted: list[dict[str, Any]] = []

    planner = update.get("planner")
    if planner:
        plan = planner.get("plan") or []
        status = planner.get("planner_status") or "continue"
        emitted.append(
            event(
                "plan",
                status=status,
                reason=planner.get("planner_reason", ""),
                plan=plan,
                next_task=planner.get("next_task", ""),
            )
        )
        if status != "continue":
            emitted.append(event("final", text=planner.get("final", "")))

    executor = update.get("executor")
    if executor:
        status = executor.get("executor_status") or "continue"
        reason = executor.get("executor_reason") or ""
        command = executor.get("browser_command", "")
        if status != "continue":
            emitted.append(
                event(
                    "executor",
                    status=status,
                    reason=reason,
                    thought=executor.get("executor_thought", ""),
                )
            )
            return emitted

        emitted.append(
            event(
                "action",
                tool="agent-browser",
                command=command,
                thought=executor.get("executor_thought", ""),
            )
        )
        observations = executor.get("observations") or []
        if observations:
            latest = observations[-1]
            emitted.append(
                event(
                    "observation",
                    command=latest.get("command", ""),
                    ok=bool(latest.get("ok")),
                    output=_clean_text(latest.get("output") or latest.get("error")),
                    success_criteria=latest.get("success_criteria", ""),
                )
            )

    return emitted


async def run_agent_prompt(
    prompt: str,
    thread_id: str | None = None,
    max_steps: int = 40,
    api_key: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if not prompt.strip():
        yield event("error", message="prompt is required")
        return

    token = set_request_api_key(api_key)
    has_api_key = bool(api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    if not has_api_key:
        reset_request_api_key(token)
        yield event(
            "error",
            message=(
                "No Gemini API key found. Export GEMINI_API_KEY before running "
                "`wolfie`, or restart the daemon after setting it."
            ),
        )
        return

    thread = thread_id or f"wolfie-{uuid.uuid4().hex[:8]}"
    try:
        yield event("status", message="starting LangGraph browser agent", thread_id=thread)

        yield event("status", message="connecting agent-browser to 127.0.0.1:9222")
        connect_result = await asyncio.to_thread(agent_browser, "connect 9222")
        if connect_result.get("status") != "success":
            yield event(
                "error",
                message=(
                    "agent-browser could not connect to CDP port 9222. "
                    "Run `start` first, then retry `prompt <task>`."
                ),
                detail=_clean_text(
                    connect_result.get("error")
                    or connect_result.get("reason")
                    or connect_result.get("logs")
                ),
            )
            return

        try:
            graph = build_graph()
        except AgentDependencyError as exc:
            yield event("error", message=str(exc))
            return

        state = initial_state(
            prompt=prompt.strip(),
            thread_id=thread,
            max_steps=max(1, min(max_steps, 50)),
            profile_dir=str(USER_DATA_DIR),
        )
        config = {"configurable": {"thread_id": thread}}

        try:
            async for update in graph.astream(state, config=config, stream_mode="updates"):
                for payload in _events_from_update(update):
                    yield payload
            yield event("done", thread_id=thread)
        except Exception as exc:
            yield event("error", message=str(exc), thread_id=thread)
    finally:
        reset_request_api_key(token)
