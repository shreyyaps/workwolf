import json
import os
import shlex
import subprocess
import urllib.request
from pathlib import Path
from shutil import which
import socket
import time
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
USER_DATA_DIR = ROOT_DIR / "user-data"
LOGIN_SENTINEL = USER_DATA_DIR / ".wolfie-login-complete"
LOGIN_URL = "https://myaccount.google.com/"
INSTALL_DIR = Path.home() / ".toolname"
NODE_BIN_DIR = INSTALL_DIR / "node" / "bin"
NPM_GLOBAL_PREFIX = INSTALL_DIR / "npm-global"
AGENT_BROWSER_PACKAGE = "agent-browser"


_CHROME_CANDIDATES = [
    "google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
]


def _runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    path_parts = [str(NPM_GLOBAL_PREFIX / "bin")]
    if NODE_BIN_DIR.exists():
        path_parts.append(str(NODE_BIN_DIR))
    if env.get("PATH"):
        path_parts.append(env["PATH"])
    env["PATH"] = os.pathsep.join(path_parts)
    return env


def _check_node_installed() -> tuple[bool, str | None]:
    """Check if Node.js is installed."""
    node_path = which("node", path=_runtime_env().get("PATH"))
    return (node_path is not None, node_path)


def _check_npm_installed() -> tuple[bool, str | None]:
    """Check if npm is installed."""
    npm_path = which("npm", path=_runtime_env().get("PATH"))
    return (npm_path is not None, npm_path)


def _agent_browser_binary() -> str | None:
    return which("agent-browser", path=_runtime_env().get("PATH"))


def _npm_has_agent_browser(npm_path: str) -> bool:
    result = subprocess.run(
        [
            npm_path,
            "list",
            "-g",
            AGENT_BROWSER_PACKAGE,
            "--depth=0",
            "--prefix",
            str(NPM_GLOBAL_PREFIX),
        ],
        env=_runtime_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _install_agent_browser(npm_path: str) -> subprocess.CompletedProcess[str]:
    """Install agent-browser globally via npm."""
    NPM_GLOBAL_PREFIX.mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        [
            npm_path,
            "install",
            "-g",
            AGENT_BROWSER_PACKAGE,
            "--prefix",
            str(NPM_GLOBAL_PREFIX),
        ],
        env=_runtime_env(),
        capture_output=True,
        text=True,
        check=False,
    )


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


def _login_completed() -> bool:
    return LOGIN_SENTINEL.is_file()


def _mark_login_complete() -> None:
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGIN_SENTINEL.touch()


def _list_cdp_pages(host: str = "127.0.0.1", port: int = 9222) -> list[dict] | None:
    try:
        with urllib.request.urlopen(
            f"http://{host}:{port}/json/list", timeout=2.0
        ) as resp:
            data = json.loads(resp.read())
        return data if isinstance(data, list) else []
    except Exception:
        return None


def _wait_for_login_window_closed(timeout_seconds: float = 30 * 60) -> bool:
    # On macOS, closing the Chrome window does not terminate the Chrome
    # process (app stays alive in the menu bar). So we can't rely on
    # proc.wait(). Instead, launch with the debug port and poll CDP — when
    # the page list is empty, the user has closed all tabs.
    deadline = time.time() + timeout_seconds
    saw_any_page = False
    while time.time() < deadline:
        pages = _list_cdp_pages()
        if pages is None:
            # CDP gone — Chrome fully exited. Treat as done iff we'd seen
            # the login page at least once (otherwise CDP probably never
            # came up).
            return saw_any_page
        page_targets = [p for p in pages if p.get("type") == "page"]
        if page_targets:
            saw_any_page = True
        elif saw_any_page:
            return True
        time.sleep(1.0)
    return False


def _run_first_time_login(chrome_path: str) -> None:
    _terminate_existing_chrome_with_profile()
    subprocess.Popen(
        [
            chrome_path,
            "--remote-debugging-port=9222",
            f"--user-data-dir={USER_DATA_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            LOGIN_URL,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_for_cdp_ready():
        _terminate_existing_chrome_with_profile()
        return
    if not _wait_for_login_window_closed():
        _terminate_existing_chrome_with_profile()
        return
    _terminate_existing_chrome_with_profile()
    _mark_login_complete()


def _ensure_agent_browser_ready() -> dict[str, Any]:
    """Ensure agent-browser is installed and ready. Returns status dict."""
    logs: list[dict[str, Any]] = [
        {"level": "info", "message": "Checking Node.js runtime..."}
    ]
    node_installed, node_path = _check_node_installed()
    logs.append(
        {
            "level": "success" if node_installed else "error",
            "message": (
                f"Node.js found at {node_path}"
                if node_installed
                else "Node.js was not found"
            ),
        }
    )

    logs.append({"level": "info", "message": "Checking npm..."})
    npm_installed, npm_path = _check_npm_installed()
    logs.append(
        {
            "level": "success" if npm_installed else "error",
            "message": f"npm found at {npm_path}" if npm_installed else "npm was not found",
        }
    )

    if not node_installed or not npm_installed:
        return {
            "status": "error",
            "reason": "node_npm_not_installed",
            "logs": logs,
        }

    logs.append({"level": "info", "message": "Checking agent-browser binary..."})
    agent_browser_path = _agent_browser_binary()
    if agent_browser_path:
        logs.append(
            {
                "level": "success",
                "message": f"agent-browser found at {agent_browser_path}",
            }
        )
        return {
            "status": "ready",
            "logs": logs,
            "agent_browser_path": agent_browser_path,
        }

    logs.append(
        {
            "level": "warning",
            "message": "agent-browser was not found on PATH",
        }
    )
    logs.append(
        {
            "level": "info",
            "message": f"Checking npm prefix {NPM_GLOBAL_PREFIX}...",
        }
    )
    if npm_path and _npm_has_agent_browser(npm_path):
        logs.append(
            {
                "level": "warning",
                "message": "npm reports agent-browser installed, but the binary is not on PATH",
            }
        )

    logs.append(
        {
            "level": "info",
            "message": (
                "Installing agent-browser with npm: "
                f"npm install -g {AGENT_BROWSER_PACKAGE} --prefix {NPM_GLOBAL_PREFIX}"
            ),
        }
    )
    install_result = _install_agent_browser(npm_path)
    if install_result.returncode == 0:
        installed_path = _agent_browser_binary()
        logs.append(
            {"level": "success", "message": "agent-browser installed successfully"}
        )
        if installed_path:
            logs.append(
                {"level": "success", "message": f"agent-browser ready at {installed_path}"}
            )
            return {
                "status": "ready",
                "logs": logs,
                "agent_browser_path": installed_path,
            }
        logs.append(
            {
                "level": "error",
                "message": "npm install finished but agent-browser was not found on PATH",
            }
        )
        return {
            "status": "error",
            "reason": "binary_not_found_after_install",
            "logs": logs,
        }

    npm_error = install_result.stderr.strip() or install_result.stdout.strip()
    logs.append({"level": "error", "message": "Failed to install agent-browser"})
    if npm_error:
        logs.append({"level": "error", "message": npm_error})
    return {
        "status": "error",
        "reason": "installation_failed",
        "logs": logs,
    }


def _run_agent_browser_command(cmd: str) -> dict[str, Any]:
    """Run a command through agent-browser."""
    try:
        args = shlex.split(cmd)
    except ValueError as e:
        return {
            "status": "error",
            "reason": "parse_error",
            "error": str(e),
        }

    try:
        result = subprocess.run(
            ["agent-browser", *args],
            env=_runtime_env(),
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


def run_agent_browser_cli_command(cmd: str) -> dict[str, Any]:
    """Run an agent-browser CLI command after checking the local install."""
    ready_status = _ensure_agent_browser_ready()
    if ready_status["status"] != "ready":
        return ready_status
    result = _run_agent_browser_command(cmd)
    return _attach_logs(result, ready_status.get("logs", []))


def _attach_logs(result: dict[str, Any], logs: list[dict[str, Any]]) -> dict[str, Any]:
    if logs:
        result["logs"] = logs + result.get("logs", [])
    return result


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
        return _attach_logs(result, ready_status.get("logs", []))

    # Passthrough: anything starting with `agent-browser` runs as-is on the
    # shell. No subcommand validation — for fast manual testing. Preserves
    # the user's exact quoting by stripping the prefix from the raw string
    # rather than re-joining shlex-split args.
    if cmd == "agent-browser":
        rest = normalized[len("agent-browser"):].strip()
        return run_agent_browser_cli_command(rest)

    if cmd == "needs_login":
        return {"status": "ready", "needs_login": not _login_completed()}

    chrome_path = _ensure_chrome_installed()
    if chrome_path is None:
        return {
            "status": "error",
            "reason": "chrome_not_found",
            "message": "Google Chrome not found on system",
        }

    if cmd == "init":
        # Force re-login: clear the sentinel so the next `start` re-prompts.
        if LOGIN_SENTINEL.exists():
            LOGIN_SENTINEL.unlink()
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
        logs: list[dict[str, Any]] = []

        # Ensure agent-browser is installed before starting
        ready_status = _ensure_agent_browser_ready()
        logs.extend(ready_status.get("logs", []))
        if ready_status["status"] != "ready":
            return ready_status

        if not _login_completed():
            logs.append(
                {"level": "info", "message": "🔐 No sign-in on file — opening login window..."}
            )
            _run_first_time_login(chrome_path)
            if not _login_completed():
                return {
                    "status": "error",
                    "reason": "login_not_completed",
                    "message": "Sign-in window closed without completing login. Try `start` again.",
                    "logs": logs,
                }
            logs.append(
                {"level": "success", "message": "✓ Sign-in saved to ./user-data/"}
            )
        else:
            logs.append(
                {"level": "success", "message": "✓ Sign-in already on file"}
            )

        logs.append(
            {"level": "info", "message": "🚀 Launching Chrome on debug port 9222..."}
        )
        _terminate_existing_chrome_with_profile()

        # `about:blank` as the start URL gives agent-browser a normal page
        # to target after `connect 9222`. Without this, Chrome may restore
        # `chrome://newtab/` from the previous session and agent-browser
        # picks that — navigating *from* a chrome:// URL to an external URL
        # is rejected by Chrome with ERR_BLOCKED_BY_CLIENT.
        # `--disable-features=Glic,GlicRollout` shuts off Chrome's built-in
        # Gemini sidebar, which otherwise installs a webRequest intercepter
        # and creates extra chrome:// targets in the CDP page list.
        chrome_args = [
            chrome_path,
            "--remote-debugging-port=9222",
            f"--user-data-dir={USER_DATA_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Glic,GlicRollout,GlicPanel",
            "about:blank",
        ]
        chrome_process = subprocess.Popen(
            chrome_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        logs.append(
            {"level": "info", "message": "Waiting for CDP on 127.0.0.1:9222..."}
        )
        if not _wait_for_cdp_ready():
            logs.append(
                {
                    "level": "warning",
                    "message": "CDP was not ready on the first attempt; restarting Chrome...",
                }
            )
            _terminate_existing_chrome_with_profile()
            chrome_process = subprocess.Popen(
                chrome_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logs.append(
                {
                    "level": "info",
                    "message": "Waiting for CDP on 127.0.0.1:9222 after restart...",
                }
            )

        if not _wait_for_cdp_ready():
            return {
                "status": "error",
                "reason": "cdp_not_ready",
                "message": "Failed to initialize browser debugging protocol",
                "logs": logs,
            }
        logs.append(
            {"level": "success", "message": "✓ CDP ready on 127.0.0.1:9222"}
        )

        # Auto-connect agent-browser to the debug port so subsequent
        # `agent` / `agent-browser` calls target the headed Chrome instead
        # of spinning up a fresh Playwright instance.
        logs.append(
            {
                "level": "info",
                "message": "Connecting agent-browser to 127.0.0.1:9222...",
            }
        )
        connect_result = _run_agent_browser_command("connect 9222")
        agent_connected = connect_result.get("status") == "success"
        if agent_connected:
            logs.append(
                {
                    "level": "success",
                    "message": "agent-browser connected to 127.0.0.1:9222",
                }
            )
        else:
            connect_error = (
                connect_result.get("error")
                or connect_result.get("reason")
                or "unknown error"
            )
            logs.append(
                {
                    "level": "warning",
                    "message": (
                        "agent-browser connect failed; "
                        f"run `agent-browser connect 9222` manually ({connect_error})"
                    ),
                }
            )

        return {
            "status": "started",
            "message": "✓ Browser connected and ready!\n💡 Try: agent screenshot",
            "pid": chrome_process.pid,
            "debug_port": 9222,
            "agent_connected": agent_connected,
            "logs": logs,
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
