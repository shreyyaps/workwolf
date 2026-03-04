import asyncio

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from browser.playwright_runner import (
    complete_setup_and_start_browser_session,
    ensure_browser_session_started_with_setup_page,
    get_agent_connect_logs,
    stop_browser_session,
)

router = APIRouter()


async def fake_stream(args: list[str]):
    for word in args:
        yield word
        await asyncio.sleep(0.3)


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/run-stream")
async def run_stream(payload: dict, request: Request):
    command = payload.get("command")
    args = payload.get("args", [])
    if command is None and isinstance(args, list) and args:
        command = args[0]

    if command != "start":
        raise HTTPException(
            status_code=400,
            detail="Only start command is supported on /run-stream",
        )

    setup_page_url = str(request.url_for("browser_setup_page"))

    try:
        result = await ensure_browser_session_started_with_setup_page(setup_page_url)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    status = result.get("status")
    if status == "setup_required":
        chunks = [
            "Profile setup is required.\n",
            f"Open and finish login, then click Start Agent in: {setup_page_url}\n",
        ]
    elif status == "awaiting_setup_completion":
        chunks = [
            "Setup browser already running.\n",
            f"After login, click Start Agent in: {setup_page_url}\n",
        ]
    elif status == "already_running":
        chunks = ["Agent browser is already running.\n"]
    else:
        chunks = ["Agent browser started.\n"]

    # Give the agent connect process a brief moment to emit startup logs.
    await asyncio.sleep(1.2)
    logs = get_agent_connect_logs(limit=30)
    if logs:
        chunks.append("Agent connect logs:\n")
        chunks.extend([f"{line}\n" for line in logs])
    else:
        chunks.append("Agent connect logs: (no output yet)\n")

    return StreamingResponse(fake_stream(chunks), media_type="text/plain")


@router.get("/browser/setup-page", response_class=HTMLResponse, name="browser_setup_page")
async def browser_setup_page():
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Wolfie Browser Setup</title>
  <style>
    body { font-family: sans-serif; margin: 40px; line-height: 1.5; }
    button { padding: 10px 16px; font-size: 16px; cursor: pointer; }
    #status { margin-top: 16px; white-space: pre-line; }
  </style>
</head>
<body>
  <h2>Complete Login, Then Start Agent</h2>
  <p>1. Sign in to required accounts in any tab.</p>
  <p>2. Return here and click the button below.</p>
  <button id="startAgentBtn">Start Agent</button>
  <div id="status"></div>
  <script>
    const statusEl = document.getElementById("status");
    document.getElementById("startAgentBtn").addEventListener("click", async () => {
      statusEl.textContent = "Starting agent browser session...";
      try {
        const response = await fetch("/browser/setup-complete", { method: "POST" });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(data.detail || "Failed to start agent browser");
        }
        statusEl.textContent = "Agent session started. You can close this setup window.";
      } catch (err) {
        statusEl.textContent = "Error: " + err.message;
      }
    });
  </script>
</body>
</html>
"""


@router.post("/browser/setup-complete")
async def browser_setup_complete():
    try:
        return await complete_setup_and_start_browser_session()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/browser/stop")
async def stop_browser():
    return await stop_browser_session()
