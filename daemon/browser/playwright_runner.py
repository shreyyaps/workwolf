import asyncio
from collections import deque
from pathlib import Path
from shutil import which
import socket
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
USER_DATA_DIR = ROOT_DIR / "user-data"

_remote_debug_process: asyncio.subprocess.Process | None = None
_setup_process: asyncio.subprocess.Process | None = None
_agent_connect_process: asyncio.subprocess.Process | None = None
_agent_connect_stdout_task: asyncio.Task | None = None
_agent_connect_stderr_task: asyncio.Task | None = None
_agent_connect_logs: deque[str] = deque(maxlen=200)
_process_lock = asyncio.Lock()


def _ensure_chrome_installed() -> None:
    if which("google-chrome") is None:
        raise RuntimeError("google-chrome is not installed or not in PATH")


def _ensure_agent_browser_installed() -> None:
    if which("agent-browser") is None:
        raise RuntimeError("agent-browser is not installed or not in PATH")


def _is_running(proc: asyncio.subprocess.Process | None) -> bool:
    return proc is not None and proc.returncode is None


async def _start_remote_debug_session() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        "google-chrome",
        "--remote-debugging-port=9222",
        f"--user-data-dir={USER_DATA_DIR}",
        "--no-first-run",
        "--no-default-browser-check",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


async def _start_agent_connect_session() -> asyncio.subprocess.Process:
    _agent_connect_logs.append("[agent-browser] launching: connect 9222")
    return await asyncio.create_subprocess_exec(
        "agent-browser",
        "connect",
        "9222",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _wait_for_cdp_ready(
    host: str = "127.0.0.1", port: int = 9222, timeout_seconds: float = 12.0
) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while loop.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.4)
            if sock.connect_ex((host, port)) == 0:
                return True
        await asyncio.sleep(0.25)
    return False


async def _consume_stream(
    stream: asyncio.StreamReader | None, stream_name: str
) -> None:
    if stream is None:
        return
    while True:
        line = await stream.readline()
        if not line:
            break
        message = line.decode(errors="replace").rstrip()
        if message:
            _agent_connect_logs.append(f"[agent-browser:{stream_name}] {message}")


async def _ensure_agent_connected() -> asyncio.subprocess.Process:
    global _agent_connect_process, _agent_connect_stdout_task, _agent_connect_stderr_task
    if _is_running(_agent_connect_process):
        return _agent_connect_process

    ready = await _wait_for_cdp_ready()
    if not ready:
        _agent_connect_logs.append(
            "[agent-browser] CDP 9222 did not become ready before timeout"
        )
        raise RuntimeError("Chrome remote debugging port 9222 is not ready")

    attempts = 4
    for attempt in range(1, attempts + 1):
        _agent_connect_logs.append(f"[agent-browser] connect attempt {attempt}/{attempts}")
        _agent_connect_process = await _start_agent_connect_session()
        _agent_connect_stdout_task = asyncio.create_task(
            _consume_stream(_agent_connect_process.stdout, "stdout")
        )
        _agent_connect_stderr_task = asyncio.create_task(
            _consume_stream(_agent_connect_process.stderr, "stderr")
        )

        try:
            await asyncio.wait_for(_agent_connect_process.wait(), timeout=2.5)
        except asyncio.TimeoutError:
            # Still running after timeout: consider this connected.
            return _agent_connect_process

        rc = _agent_connect_process.returncode
        if rc == 0:
            _agent_connect_logs.append(
                "[agent-browser] connect completed successfully (exit code 0)"
            )
            return _agent_connect_process

        _agent_connect_logs.append(
            f"[agent-browser] connect exited with code {rc}"
        )
        if _agent_connect_stdout_task:
            _agent_connect_stdout_task.cancel()
            _agent_connect_stdout_task = None
        if _agent_connect_stderr_task:
            _agent_connect_stderr_task.cancel()
            _agent_connect_stderr_task = None
        _agent_connect_process = None
        await asyncio.sleep(0.7)

    raise RuntimeError("agent-browser connect 9222 failed after retries")


def get_agent_connect_logs(limit: int = 40) -> list[str]:
    if limit <= 0:
        return []
    return list(_agent_connect_logs)[-limit:]


async def ensure_browser_session_started_with_setup_page(
    setup_page_url: str,
) -> dict[str, Any]:
    global _remote_debug_process, _setup_process
    async with _process_lock:
        _ensure_chrome_installed()
        _ensure_agent_browser_installed()

        if _is_running(_remote_debug_process):
            agent_process = await _ensure_agent_connected()
            return {
                "status": "already_running",
                "remote_debugging_port": 9222,
                "user_data_dir": str(USER_DATA_DIR),
                "agent_connect_pid": agent_process.pid,
            }

        if _is_running(_setup_process):
            return {
                "status": "awaiting_setup_completion",
                "setup_page": setup_page_url,
                "user_data_dir": str(USER_DATA_DIR),
            }

        if not USER_DATA_DIR.exists():
            _setup_process = await asyncio.create_subprocess_exec(
                "google-chrome",
                f"--user-data-dir={USER_DATA_DIR}",
                setup_page_url,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            return {
                "status": "setup_required",
                "setup_page": setup_page_url,
                "user_data_dir": str(USER_DATA_DIR),
                "pid": _setup_process.pid,
            }

        _remote_debug_process = await _start_remote_debug_session()
        agent_process = await _ensure_agent_connected()
        return {
            "status": "started",
            "remote_debugging_port": 9222,
            "user_data_dir": str(USER_DATA_DIR),
            "pid": _remote_debug_process.pid,
            "agent_connect_pid": agent_process.pid,
        }


async def complete_setup_and_start_browser_session() -> dict[str, Any]:
    global _remote_debug_process, _setup_process
    async with _process_lock:
        _ensure_chrome_installed()
        _ensure_agent_browser_installed()

        if _is_running(_remote_debug_process):
            agent_process = await _ensure_agent_connected()
            return {
                "status": "already_running",
                "remote_debugging_port": 9222,
                "user_data_dir": str(USER_DATA_DIR),
                "agent_connect_pid": agent_process.pid,
            }

        if _is_running(_setup_process):
            _setup_process.terminate()
            try:
                await asyncio.wait_for(_setup_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                _setup_process.kill()
                await _setup_process.wait()
            finally:
                _setup_process = None

        if not USER_DATA_DIR.exists():
            raise RuntimeError(
                f"user-data folder was not created at {USER_DATA_DIR}"
            )

        _remote_debug_process = await _start_remote_debug_session()
        agent_process = await _ensure_agent_connected()
        return {
            "status": "started",
            "remote_debugging_port": 9222,
            "user_data_dir": str(USER_DATA_DIR),
            "pid": _remote_debug_process.pid,
            "agent_connect_pid": agent_process.pid,
        }


async def stop_browser_session() -> dict[str, Any]:
    global _remote_debug_process, _setup_process, _agent_connect_process
    global _agent_connect_stdout_task, _agent_connect_stderr_task
    async with _process_lock:
        if _is_running(_setup_process):
            _setup_process.terminate()
            try:
                await asyncio.wait_for(_setup_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                _setup_process.kill()
                await _setup_process.wait()
            finally:
                _setup_process = None

        if _is_running(_agent_connect_process):
            _agent_connect_process.terminate()
            try:
                await asyncio.wait_for(_agent_connect_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                _agent_connect_process.kill()
                await _agent_connect_process.wait()
            finally:
                _agent_connect_process = None
                if _agent_connect_stdout_task:
                    _agent_connect_stdout_task.cancel()
                    _agent_connect_stdout_task = None
                if _agent_connect_stderr_task:
                    _agent_connect_stderr_task.cancel()
                    _agent_connect_stderr_task = None

        if _is_running(_remote_debug_process):
            _remote_debug_process.terminate()
            try:
                await asyncio.wait_for(_remote_debug_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                _remote_debug_process.kill()
                await _remote_debug_process.wait()
            finally:
                _remote_debug_process = None

        return {"status": "stopped"}
