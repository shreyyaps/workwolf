from typing import Any

from llm_orchestration_langgraph.functions.agent_browser_vercel import (
    run_agent_browser_cli_command,
)


def agent_browser(command: str) -> dict[str, Any]:
    """Run one agent-browser CLI command against Wolfie's connected browser."""
    normalized = command.strip()
    if normalized == "agent-browser":
        normalized = ""
    if normalized.startswith("agent-browser "):
        normalized = normalized[len("agent-browser ") :].strip()
    return run_agent_browser_cli_command(normalized)
