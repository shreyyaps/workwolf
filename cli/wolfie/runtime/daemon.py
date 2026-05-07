import subprocess
import time
from pathlib import Path

import httpx

from ..core.config import DAEMON_HEALTH, console
from .node import runtime_env


def is_daemon_running() -> bool:
    try:
        response = httpx.get(DAEMON_HEALTH, timeout=1.0)
        return response.status_code == 200
    except Exception:
        return False


def start_daemon() -> None:
    console.print("[dim]Starting Wolfie daemon...[/dim]")

    # Use absolute path for daemon/main.py
    daemon_main = Path(__file__).resolve().parents[3] / "daemon" / "main.py"

    process = subprocess.Popen(
        [
            "uv",
            "run",
            "fastapi",
            "dev",
            str(daemon_main),
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
        env=runtime_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Give it a moment to start or fail
    time.sleep(1)
    poll_result = process.poll()

    if poll_result is not None:
        # Process exited immediately, show error
        _, stderr = process.communicate()
        if stderr:
            console.print(f"[red]Daemon error: {stderr[:200]}[/red]")


def ensure_daemon() -> None:
    if is_daemon_running():
        console.print("[dim]Daemon already running.[/dim]")
        return

    start_daemon()

    for _ in range(60):
        if is_daemon_running():
            console.print("[green]✓ Daemon ready[/green]")
            return
        time.sleep(0.25)

    console.print("[red]✗ Failed to start daemon[/red]")
