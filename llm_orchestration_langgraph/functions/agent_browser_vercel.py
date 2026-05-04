import json
import shlex
import subprocess
from pathlib import Path
from shutil import which
import socket
import time
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
USER_DATA_DIR = ROOT_DIR / "user-data"


_CHROME_CANDIDATES = [
    "google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
]


def _check_node_installed() -> tuple[bool, str | None]:
    """Check if Node.js is installed."""
    node_path = which("node")
    return (node_path is not None, node_path)


def _check_npm_installed() -> tuple[bool, str | None]:
    """Check if npm is installed."""
    npm_path = which("npm")
    return (npm_path is not None, npm_path)


def _check_agent_browser_installed() -> bool:
    """Check if agent-browser is installed globally."""
    result = subprocess.run(
        ["npm", "list", "-g", "agent-browser"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _install_agent_browser() -> bool:
    """Install agent-browser globally via npm."""
    result = subprocess.run(
        ["npm", "install", "-g", "agent-browser"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _ensure_chrome_installed() -> str | None:
    for candidate in _CHROME_CANDIDATES:
        found = which(candidate) or (Path(candidate).is_file() and candidate) or None
        if found:
            return found
    return None


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

    chrome_path = _ensure_chrome_installed()
    if not chrome_path:
        raise RuntimeError("google-chrome not found")

    # Open Chrome to initialize the user-data directory
    proc = subprocess.Popen(
        [
            chrome_path,
            f"--user-data-dir={USER_DATA_DIR}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait a bit for profile to initialize
    time.sleep(2)
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


def _ensure_agent_browser_ready() -> dict[str, Any]:
    """Ensure agent-browser is installed and ready. Returns status dict."""
    node_installed, _ = _check_node_installed()
    npm_installed, _ = _check_npm_installed()

    if not node_installed or not npm_installed:
        return {
            "status": "error",
            "reason": "node_npm_not_installed",
            "logs": [
                {
                    "level": "error",
                    "message": f"Node.js: {'✓ installed' if node_installed else '✗ NOT installed'}",
                },
                {
                    "level": "error",
                    "message": f"npm: {'✓ installed' if npm_installed else '✗ NOT installed'}",
                },
            ],
        }

    if _check_agent_browser_installed():
        return {
            "status": "ready",
            "logs": [{"level": "success", "message": "✓ agent-browser is installed"}],
        }

    # Try to install agent-browser
    logs = [
        {"level": "info", "message": "📦 Installing agent-browser globally..."}
    ]

    if _install_agent_browser():
        logs.append(
            {"level": "success", "message": "✓ agent-browser installed successfully"}
        )
        return {"status": "ready", "logs": logs}
    else:
        logs.append(
            {"level": "error", "message": "✗ Failed to install agent-browser"}
        )
        return {
            "status": "error",
            "reason": "installation_failed",
            "logs": logs,
        }


def _run_agent_browser_command(cmd: str) -> dict[str, Any]:
    """Run a command through agent-browser."""
    try:
        result = subprocess.run(
            f"agent-browser {cmd}",
            shell=True,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        if result.returncode == 0:
            try:
                output = json.loads(result.stdout)
                return {"status": "success", "data": output}
            except json.JSONDecodeError:
                return {"status": "success", "data": result.stdout.strip()}
        else:
            return {
                "status": "error",
                "reason": "command_failed",
                "error": result.stderr.strip(),
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "reason": "timeout",
            "error": "Command timed out after 30 seconds",
        }
    except Exception as e:
        return {
            "status": "error",
            "reason": "execution_error",
            "error": str(e),
        }


def run_agent_browser_vercel_command(user_command: str) -> dict[str, Any]:
    normalized = user_command.strip()
    if not normalized:
        return {
            "status": "ignored",
            "reason": "empty_command",
            "received": user_command,
        }

    try:
        args = shlex.split(normalized)
    except ValueError:
        return {
            "status": "error",
            "reason": "parse_error",
            "message": "Invalid command syntax",
        }

    if not args:
        return {
            "status": "ignored",
            "reason": "empty_command",
            "received": user_command,
        }

    cmd = args[0]
    remaining_args = args[1:] if len(args) > 1 else []

    # Handle agent commands (Vercel browser agent)
    if cmd == "agent":
        if not remaining_args:
            return {
                "status": "error",
                "reason": "missing_agent_command",
                "message": "Usage: agent <command> [args]",
            }

        # Build the agent-browser command
        agent_cmd = " ".join(remaining_args)

        # Ensure agent-browser is ready
        ready_status = _ensure_agent_browser_ready()
        if ready_status["status"] != "ready":
            return ready_status

        # Execute the agent-browser command
        result = _run_agent_browser_command(agent_cmd)
        return result

    chrome_path = _ensure_chrome_installed()
    if chrome_path is None:
        return {
            "status": "error",
            "reason": "chrome_not_found",
            "message": "Google Chrome not found on system",
        }

    if cmd == "init":
        # First-time setup: open browser for user to login
        _ensure_user_data_initialized()
        _terminate_existing_chrome_with_profile()

        chrome_args = [
            chrome_path,
            f"--user-data-dir={USER_DATA_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        chrome_process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        return {
            "status": "awaiting_login",
            "message": "🔐 Browser opened for login. Complete your login and then type: start",
            "pid": chrome_process.pid,
        }

    if cmd == "start":
        # Ensure agent-browser is installed before starting
        ready_status = _ensure_agent_browser_ready()
        if ready_status["status"] != "ready":
            return ready_status

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
                "message": "Failed to initialize browser debugging protocol",
            }

        return {
            "status": "started",
            "message": "✓ Browser connected and ready!\n💡 Try: agent screenshot",
            "pid": chrome_process.pid,
            "debug_port": 9222,
        }

    if cmd == "open":
        if not remaining_args:
            return {
                "status": "error",
                "reason": "missing_url",
                "message": "Usage: open <url>",
            }
        url = remaining_args[0]
        chrome_args = [
            chrome_path,
            f"--user-data-dir={USER_DATA_DIR}",
            url,
        ]
        process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            "status": "started",
            "message": f"🌐 Opening {url}",
            "pid": process.pid,
        }

    return {
        "status": "error",
        "reason": "unsupported_command",
        "message": f"Unknown command: {cmd}",
        "hint": "Use 'help' to see available commands",
    }
