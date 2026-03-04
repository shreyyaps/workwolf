import subprocess
import time

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
    console.print("[yellow]Starting Wolfie daemon...[/yellow]")

    subprocess.Popen(
        [
            "uv",
            "run",
            "uvicorn",
            "daemon.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
        ],
        env=runtime_env(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_daemon() -> None:
    if is_daemon_running():
        return

    start_daemon()

    for _ in range(30):
        if is_daemon_running():
            console.print("[green]Wolfie daemon ready.[/green]")
            return
        time.sleep(0.5)

    console.print("[red]Failed to start daemon.[/red]")
