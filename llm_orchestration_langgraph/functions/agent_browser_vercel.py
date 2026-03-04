import subprocess
from typing import Any

EXPECTED_COMMAND = "open https://mail.google.com/mail"


def run_agent_browser_vercel_command(user_command: str) -> dict[str, Any]:
    normalized = user_command.strip()
    if normalized != EXPECTED_COMMAND:
        return {
            "status": "ignored",
            "reason": "unsupported_command",
            "expected": EXPECTED_COMMAND,
            "received": user_command,
        }

    process = subprocess.Popen(
        ["agent-browser", "open", "https://mail.google.com/mail"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return {
        "status": "started",
        "pid": process.pid,
        "executed": "agent-browser open https://mail.google.com/mail",
    }
