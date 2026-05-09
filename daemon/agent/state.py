from typing import Any, TypedDict


class ConversationMessage(TypedDict, total=False):
    role: str
    content: str


class BrowserObservation(TypedDict, total=False):
    command: str
    skipped: bool
    side_effect: bool
    ok: bool
    output: Any
    error: str
    success_criteria: str
    validation_command: str
    validation_commands: list[str]
    validation_ok: bool
    validation_output: Any
    validation_error: str
    validation_results: list[dict[str, Any]]


class AgentState(TypedDict, total=False):
    thread_id: str
    user_prompt: str
    max_steps: int
    step_count: int
    profile_dir: str
    cdp_host: str
    cdp_port: int
    conversation: list[ConversationMessage]
    user_feedback: str
    task_status: str
    plan: list[str]
    planner_status: str
    planner_reason: str
    next_task: str
    pending_question: str
    pending_choices: list[str]
    executor_status: str
    executor_reason: str
    executor_thought: str
    browser_command: str
    validation_command: str
    validation_commands: list[str]
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
        "conversation": [{"role": "user", "content": prompt}],
        "user_feedback": "",
        "task_status": "running",
        "plan": [],
        "pending_question": "",
        "pending_choices": [],
        "observations": [],
    }
