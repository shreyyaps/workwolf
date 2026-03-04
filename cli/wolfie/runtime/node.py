import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

from ..ui.runtime_messages import (
    show_agent_browser_installed,
    show_agent_browser_installing,
    show_node_detected,
    show_node_download,
    show_node_extract,
    show_node_installed,
)

NODE_VERSION = "v20.11.1"
NODE_URL = f"https://nodejs.org/dist/{NODE_VERSION}/node-{NODE_VERSION}-linux-x64.tar.xz"
AGENT_BROWSER_PACKAGE = "agent-browser"

INSTALL_DIR = Path.home() / ".toolname"
ARCHIVE_PATH = INSTALL_DIR / "node.tar.xz"
EXTRACTED_DIR = INSTALL_DIR / f"node-{NODE_VERSION}-linux-x64"
NODE_DIR = INSTALL_DIR / "node"
NODE_BIN = NODE_DIR / "bin" / "node"
NPM_BIN = NODE_DIR / "bin" / "npm"
NPM_GLOBAL_PREFIX = INSTALL_DIR / "npm-global"


def _run_version(binary: str) -> str | None:
    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        version = result.stdout.strip()
        return version or None
    except Exception:
        return None


def _local_node_version() -> str | None:
    if not NODE_BIN.exists():
        return None
    return _run_version(str(NODE_BIN))


def _system_node_version() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    return _run_version(node)


def _cleanup_tmp() -> None:
    if ARCHIVE_PATH.exists():
        ARCHIVE_PATH.unlink()
    if EXTRACTED_DIR.exists():
        shutil.rmtree(EXTRACTED_DIR, ignore_errors=True)


def install_node() -> None:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    show_node_download(NODE_VERSION)
    urllib.request.urlretrieve(NODE_URL, ARCHIVE_PATH)

    show_node_extract()
    with tarfile.open(ARCHIVE_PATH) as tar:
        tar.extractall(INSTALL_DIR)

    if NODE_DIR.exists():
        shutil.rmtree(NODE_DIR, ignore_errors=True)
    os.rename(EXTRACTED_DIR, NODE_DIR)

    _cleanup_tmp()
    show_node_installed()


def ensure_node() -> None:
    # Prefer machine-level Node if available.
    system_version = _system_node_version()
    if system_version is not None:
        show_node_detected(system_version)
        return

    local_version = _local_node_version()
    if local_version == NODE_VERSION:
        return

    install_node()


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    path = env.get("PATH", "")
    path_parts = [str(NPM_GLOBAL_PREFIX / "bin")]

    if NODE_BIN.exists():
        path_parts.append(str(NODE_DIR / "bin"))

    if path:
        path_parts.append(path)

    env["PATH"] = ":".join(path_parts)
    return env


def ensure_agent_browser() -> None:
    env = runtime_env()
    if shutil.which("agent-browser", path=env.get("PATH")):
        return

    npm_binary = shutil.which("npm", path=env.get("PATH"))
    if npm_binary is None:
        install_node()
        env = runtime_env()
        npm_binary = shutil.which("npm", path=env.get("PATH"))

    if npm_binary is None:
        raise RuntimeError("npm is not available to install agent-browser")

    NPM_GLOBAL_PREFIX.mkdir(parents=True, exist_ok=True)
    show_agent_browser_installing()
    result = subprocess.run(
        [
            npm_binary,
            "install",
            "-g",
            AGENT_BROWSER_PACKAGE,
            "--prefix",
            str(NPM_GLOBAL_PREFIX),
        ],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to install agent-browser")

    if not shutil.which("agent-browser", path=runtime_env().get("PATH")):
        raise RuntimeError("agent-browser install finished but binary was not found")

    show_agent_browser_installed()


def ensure_runtime_dependencies() -> None:
    ensure_node()
    ensure_agent_browser()
