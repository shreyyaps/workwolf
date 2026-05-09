from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .state import AgentState


_SESSIONS: dict[str, dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_session_state(
    thread_id: str,
    state: AgentState,
    status: str | None = None,
) -> None:
    existing = _SESSIONS.get(thread_id, {})
    _SESSIONS[thread_id] = {
        "thread_id": thread_id,
        "created_at": existing.get("created_at") or _now(),
        "updated_at": _now(),
        "status": status or state.get("task_status") or existing.get("status") or "running",
        "state": deepcopy(state),
    }


def get_session_state(thread_id: str) -> AgentState | None:
    session = _SESSIONS.get(thread_id)
    if not session:
        return None
    return deepcopy(session["state"])


def apply_user_input(
    state: AgentState,
    message: str,
    max_steps: int | None = None,
) -> AgentState:
    updated: AgentState = deepcopy(state)
    conversation = list(updated.get("conversation", []))
    conversation.append({"role": "user", "content": message.strip()})
    updated["conversation"] = conversation
    updated["user_feedback"] = message.strip()
    updated["task_status"] = "running"
    updated["planner_status"] = ""
    updated["planner_reason"] = ""
    updated["pending_question"] = ""
    updated["pending_choices"] = []
    updated["final"] = ""
    if max_steps is not None:
        updated["max_steps"] = max(1, min(max_steps, 50))
    return updated


def session_summary(thread_id: str) -> dict[str, Any]:
    session = _SESSIONS.get(thread_id)
    if not session:
        return {
            "status": "missing",
            "thread_id": thread_id,
            "message": "No agent session exists for this thread yet.",
        }

    state: AgentState = session["state"]
    observations = state.get("observations", [])
    latest_observation = observations[-1] if observations else None
    return {
        "status": "ready",
        "thread_id": thread_id,
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
        "task_status": state.get("task_status") or session.get("status"),
        "goal": state.get("user_prompt", ""),
        "step_count": state.get("step_count", 0),
        "max_steps": state.get("max_steps", 0),
        "plan": state.get("plan", []),
        "next_task": state.get("next_task", ""),
        "pending_question": state.get("pending_question", ""),
        "pending_choices": state.get("pending_choices", []),
        "last_action": state.get("browser_command", ""),
        "last_validation": state.get("validation_command", ""),
        "last_observation": latest_observation,
        "conversation": state.get("conversation", [])[-8:],
    }
