import sys
from pathlib import Path

from fastapi import FastAPI

# Add daemon directory to path for relative imports
_daemon_dir = Path(__file__).parent
if str(_daemon_dir) not in sys.path:
    sys.path.insert(0, str(_daemon_dir))

from middlewares.request_context import register_middlewares
from router.agent_browser_command import router as agent_browser_command_router
from router.api import router as api_router

app = FastAPI()

register_middlewares(app)
app.include_router(api_router)
app.include_router(agent_browser_command_router)
