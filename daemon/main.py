from fastapi import FastAPI

from middlewares.request_context import register_middlewares
from router.agent_browser_command import router as agent_browser_command_router
from router.api import router as api_router

app = FastAPI()

register_middlewares(app)
app.include_router(api_router)
app.include_router(agent_browser_command_router)
