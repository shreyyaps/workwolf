import sys
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

_daemon_dir = Path(__file__).resolve().parents[1]
_root_dir = _daemon_dir.parent
for _path in (_root_dir, _daemon_dir):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from agent.events import encode_event
from agent.service import run_agent_prompt

router = APIRouter()


@router.post("/agent/prompt")
async def run_agent_prompt_route(
    payload: dict,
    gemini_api_key: str | None = Header(
        default=None,
        alias="X-Wolfie-Gemini-Api-Key",
        include_in_schema=False,
    ),
):
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise HTTPException(status_code=400, detail="A prompt string is required")

    thread_id = payload.get("thread_id")
    if thread_id is not None and not isinstance(thread_id, str):
        raise HTTPException(status_code=400, detail="thread_id must be a string")

    max_steps = payload.get("max_steps", 20)
    if not isinstance(max_steps, int):
        raise HTTPException(status_code=400, detail="max_steps must be an integer")

    async def stream():
        async for event in run_agent_prompt(prompt, thread_id, max_steps, gemini_api_key):
            yield encode_event(event)

    return StreamingResponse(stream(), media_type="application/x-ndjson")
