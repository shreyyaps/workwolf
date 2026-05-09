import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

from llm_orchestration_langgraph.functions.agent_browser_vercel import USER_DATA_DIR

from .events import event
from .graph import build_graph
from .llm import AgentDependencyError, reset_request_api_key, set_request_api_key
from .sessions import (
    apply_user_input,
    get_session_state,
    save_session_state,
    session_summary,
)
from .state import AgentState, initial_state
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
        if status == "need_user":
            emitted.append(
                event(
                    "need_user",
                    question=planner.get("pending_question", "")
                    or planner.get("final", ""),
                    choices=planner.get("pending_choices", []),
                    reason=planner.get("planner_reason", ""),
                )
            )
        elif status != "continue":
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
                    validation_command=executor.get("validation_command", ""),
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
                    validation_command=latest.get("validation_command", ""),
                    validation_ok=bool(latest.get("validation_ok")),
                    validation_output=_clean_text(
                        latest.get("validation_output")
                        or latest.get("validation_error")
                    ),
                )
            )

    return emitted


def _merge_update(state: AgentState, update: dict[str, Any]) -> AgentState:
    merged: AgentState = {**state}
    for patch in update.values():
        if isinstance(patch, dict):
            merged.update(patch)
    return merged


def _has_api_key(api_key: str | None) -> bool:
    return bool(api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))


async def _preflight_browser() -> AsyncIterator[dict[str, Any]]:
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


async def _run_agent_state(
    state: AgentState,
    api_key: str | None,
) -> AsyncIterator[dict[str, Any]]:
    thread = str(state.get("thread_id") or f"wolfie-{uuid.uuid4().hex[:8]}")
    token = set_request_api_key(api_key)
    try:
        for payload in [
            event("status", message="starting LangGraph browser agent", thread_id=thread)
        ]:
            yield payload

        preflight_failed = False
        async for payload in _preflight_browser():
            yield payload
            if payload.get("type") == "error":
                preflight_failed = True
        if preflight_failed:
            return

        try:
            graph = build_graph()
        except AgentDependencyError as exc:
            yield event("error", message=str(exc))
            return

        save_session_state(thread, state, "running")
        config = {"configurable": {"thread_id": thread}}

        try:
            current_state = state
            async for update in graph.astream(
                current_state,
                config=config,
                stream_mode="updates",
            ):
                current_state = _merge_update(current_state, update)
                save_session_state(
                    thread,
                    current_state,
                    str(current_state.get("task_status") or "running"),
                )
                for payload in _events_from_update(update):
                    yield payload
            yield event("done", thread_id=thread)
        except Exception as exc:
            yield event("error", message=str(exc), thread_id=thread)
    finally:
        reset_request_api_key(token)


async def run_agent_prompt(
    prompt: str,
    thread_id: str | None = None,
    max_steps: int = 40,
    api_key: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if not prompt.strip():
        yield event("error", message="prompt is required")
        return

    if not _has_api_key(api_key):
        yield event(
            "error",
            message=(
                "No Gemini API key found. Export GEMINI_API_KEY before running "
                "`wolfie`, or restart the daemon after setting it."
            ),
        )
        return

    thread = thread_id or "default"
    state = initial_state(
        prompt=prompt.strip(),
        thread_id=thread,
        max_steps=max(1, min(max_steps, 50)),
        profile_dir=str(USER_DATA_DIR),
    )
    async for payload in _run_agent_state(state, api_key):
        yield payload


async def run_agent_input(
    message: str,
    thread_id: str | None = None,
    max_steps: int = 40,
    api_key: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if not message.strip():
        yield event("error", message="input message is required")
        return

    if not _has_api_key(api_key):
        yield event(
            "error",
            message=(
                "No Gemini API key found. Export GEMINI_API_KEY before running "
                "`wolfie`, or restart the daemon after setting it."
            ),
        )
        return

    thread = thread_id or "default"
    existing = get_session_state(thread)
    if existing is None:
        yield event(
            "error",
            message="No active agent session. Start one with `prompt <task>` first.",
            thread_id=thread,
        )
        return

    state = apply_user_input(existing, message, max_steps)
    yield event("status", message="received user input; resuming agent", thread_id=thread)
    async for payload in _run_agent_state(state, api_key):
        yield payload


def get_agent_session(thread_id: str | None = None) -> dict[str, Any]:
    return session_summary(thread_id or "default")
