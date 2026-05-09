from typing import Any, TypedDict


class BrowserObservation(TypedDict, total=False):
    command: str
    ok: bool
    output: Any
    error: str
    success_criteria: str


class AgentState(TypedDict, total=False):
    thread_id: str
    user_prompt: str
    max_steps: int
    step_count: int
    profile_dir: str
    cdp_host: str
    cdp_port: int
    plan: list[str]
    planner_status: str
    planner_reason: str
    next_task: str
    executor_status: str
    executor_reason: str
    executor_thought: str
    browser_command: str
    success_criteria: str
    observations: list[BrowserObservation]
    final: str
    error: str


def initial_state(
    prompt: str,
    thread_id: str,
    max_steps: int,
    profile_dir: str,
    cdp_host: str = "127.0.0.1",
    cdp_port: int = 9222,
) -> AgentState:
    return {
        "thread_id": thread_id,
        "user_prompt": prompt,
        "max_steps": max_steps,
        "step_count": 0,
        "profile_dir": profile_dir,
        "cdp_host": cdp_host,
        "cdp_port": cdp_port,
        "plan": [],
        "observations": [],
    }
