import shlex
import subprocess
from pathlib import Path
from shutil import which
import socket
import signal
import time
from typing import Any
from urllib.parse import quote

ROOT_DIR = Path(__file__).resolve().parents[2]
USER_DATA_DIR = ROOT_DIR / "user-data"


def _ensure_chrome_installed() -> str | None:
    return which("google-chrome")


def _build_autoclose_data_url() -> str:
    html = (
        "<!doctype html><html><head><meta charset='utf-8'/>"
        "<title>Wolfie Setup</title>"
        "<script>"
        "setTimeout(()=>{"
        "try{window.open('','_self');window.close();}catch(e){}"
        "},700);"
        "</script></head>"
        "<body>Initializing profile...</body></html>"
    )
    return "data:text/html;charset=utf-8," + quote(html)


def _close_process(proc: subprocess.Popen, timeout: float = 6.0) -> None:
    try:
        proc.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=4)
            return
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def _ensure_user_data_initialized() -> None:
    if USER_DATA_DIR.exists():
        return

    data_url = _build_autoclose_data_url()
    proc = subprocess.Popen(
        [
            "google-chrome",
            "--user-data-dir=./user-data",
            data_url,
        ],
        cwd=ROOT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    _close_process(proc)

    if not USER_DATA_DIR.exists():
        raise RuntimeError(f"user-data folder was not created at {USER_DATA_DIR}")


def _wait_for_cdp_ready(
    host: str = "127.0.0.1", port: int = 9222, timeout_seconds: float = 12.0
) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.4)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.25)
    return False


def _terminate_existing_chrome_with_profile() -> None:
    pattern = f"user-data-dir={USER_DATA_DIR}"
    result = subprocess.run(
        ["pgrep", "-f", pattern],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return
    pids = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    if not pids:
        return

    for pid in pids:
        try:
            subprocess.run(["kill", "-TERM", str(pid)], check=False)
        except Exception:
            continue
    time.sleep(1.0)
    for pid in pids:
        try:
            subprocess.run(["kill", "-0", str(pid)], check=False)
        except Exception:
            continue
        subprocess.run(["kill", "-KILL", str(pid)], check=False)


def run_agent_browser_vercel_command(user_command: str) -> dict[str, Any]:
    normalized = user_command.strip()
    if not normalized:
        return {
            "status": "ignored",
            "reason": "empty_command",
            "received": user_command,
        }

    args = shlex.split(normalized)
    if not args:
        return {
            "status": "ignored",
            "reason": "empty_command",
            "received": user_command,
        }

    cmd = args[0]
    if cmd == "agent-browser" and len(args) > 1:
        cmd = args[1]
        args = args[1:]

    chrome_path = _ensure_chrome_installed()
    if chrome_path is None:
        return {
            "status": "error",
            "reason": "chrome_not_found",
            "received": user_command,
        }

    if cmd == "open":
        if len(args) < 2:
            return {
                "status": "ignored",
                "reason": "missing_url",
                "received": user_command,
            }
        url = args[1]
        chrome_args = [
            chrome_path,
            f"--user-data-dir={USER_DATA_DIR}",
            url,
        ]
    else:
        chrome_args = []

    if cmd == "start":
        _ensure_user_data_initialized()
        _terminate_existing_chrome_with_profile()
        chrome_args = [
            chrome_path,
            "--remote-debugging-port=9222",
            f"--user-data-dir={USER_DATA_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        chrome_process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if not _wait_for_cdp_ready():
            _terminate_existing_chrome_with_profile()
            chrome_process = subprocess.Popen(
                chrome_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        if not _wait_for_cdp_ready():
            return {
                "status": "error",
                "reason": "cdp_not_ready",
                "received": user_command,
            }

        agent_process = subprocess.Popen(
            ["agent-browser", "connect", "9222"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return {
            "status": "started",
            "pid": chrome_process.pid,
            "agent_connect_pid": agent_process.pid,
            "executed": " ".join(chrome_args),
        }

    if not chrome_args:
        return {
            "status": "ignored",
            "reason": "unsupported_command",
            "received": user_command,
        }

    process = subprocess.Popen(
        chrome_args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return {
        "status": "started",
        "pid": process.pid,
        "executed": " ".join(chrome_args),
    }
