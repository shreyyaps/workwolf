import shlex
import subprocess
from typing import Any


def run_agent_browser_vercel_command(user_command: str) -> dict[str, Any]:
    normalized = user_command.strip()
    if not normalized:
        return {
            "status": "ignored",
            "reason": "empty_command",
            "received": user_command,
        }

    args = shlex.split(normalized)
    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return {
        "status": "started",
        "pid": process.pid,
        "executed": normalized,
    }
