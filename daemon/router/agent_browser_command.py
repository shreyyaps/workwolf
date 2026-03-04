import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from llm_orchestration_langgraph.functions.agent_browser_vercel import (  # noqa: E402
    run_agent_browser_vercel_command,
)

router = APIRouter()


@router.post("/run-agent-browser-vercel-command")
async def run_agent_browser_command(payload: dict):
    command = payload.get("command")
    args = payload.get("args", [])

    if command is None and isinstance(args, list) and args:
        command = " ".join(args)

    if not isinstance(command, str) or not command.strip():
        raise HTTPException(status_code=400, detail="A command string is required")

    result = run_agent_browser_vercel_command(command)
    if result.get("status") == "ignored":
        raise HTTPException(status_code=400, detail=result)

    return result
