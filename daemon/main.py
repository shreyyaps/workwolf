import sys
from pathlib import Path

from fastapi import FastAPI

# FastAPI can be launched from either the repo root or the daemon directory.
# Keep both roots importable so daemon-local modules and repo-level packages work.
_daemon_dir = Path(__file__).resolve().parent
_root_dir = _daemon_dir.parent
for _path in (_root_dir, _daemon_dir):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from middlewares.request_context import register_middlewares
from agent.env import load_env_local
from router.agent import router as agent_router
from router.agent_browser_command import router as agent_browser_command_router
from router.api import router as api_router

load_env_local()

app = FastAPI()

register_middlewares(app)
app.include_router(api_router)
app.include_router(agent_browser_command_router)
app.include_router(agent_router)
