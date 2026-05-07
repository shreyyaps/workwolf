# CLAUDE.md

Quick context for Claude Code working in this repo. For deeper detail, read
`AGENTS.md`, `docs/semantic.md`, and `docs/design-decisions.md`.

## What Wolfie is

A local, single-user CLI that lets an AI browser-automation agent
(`agent-browser`, an external npm package) drive a real Chrome window that
the human has already signed into. The Chrome profile lives at
`./user-data/` and persists across sessions.

The flow at runtime:

1. `wolfie` starts a local FastAPI daemon at `127.0.0.1:8765`.
2. The daemon manages a Chrome session launched with
   `--remote-debugging-port=9222 --user-data-dir=./user-data`.
3. `agent-browser connect 9222` (run per-command via the `agent` verb) drives
   that Chrome instance.

## Where the code lives

- `cli/wolfie/` — the `wolfie` CLI / interactive REPL.
  - `app/app.py` — entrypoint; bootstraps Node, ensures daemon, opens shell.
  - `ui/shell.py` — the prompt-toolkit REPL.
  - `client/stream.py` — POSTs commands to the daemon and renders responses.
  - `runtime/` — Node + daemon bootstrap.
  - `core/config.py` — daemon URL, console, completer.
- `daemon/` — FastAPI app on `127.0.0.1:8765`.
  - `router/api.py` — `GET /health`.
  - `router/agent_browser_command.py` — `POST /run-agent-browser-vercel-command`.
- `llm_orchestration_langgraph/functions/agent_browser_vercel.py` — the
  **single command path** that drives Chrome (subprocess + CDP poll, no
  Playwright, no LangGraph despite the folder name).
- `user-data/` — Chrome profile directory (sacred — don't delete).
- `docs/` — `semantic.md`, `design-decisions.md` — keep these closer to the
  code than the top-level README.

## Single command path

`agent_browser_vercel.py` is the only module that launches Chrome or invokes
`agent-browser`. Do not introduce parallel paths (an older
`daemon/browser/playwright_runner.py` was removed in commit `7e1cf5b`). Add new
verbs to its dispatcher inside `run_agent_browser_vercel_command`.

## REPL verbs

- `start` — self-bootstrapping. If the user hasn't logged in yet (sentinel
  missing), opens Chrome at `https://myaccount.google.com/` without the debug
  port and **blocks until the user closes the window**, then writes the
  sentinel. Then launches Chrome with `--remote-debugging-port=9222` and
  waits for CDP. Returns `{"status":"started", ...}`.
- `init` — force a re-login. Clears the sentinel and opens the profile
  window so the user can sign in to a different Google account.
- `open <url>` — opens a URL on the saved profile (no debug port).
- `agent <cmd>` — runs `agent-browser <cmd>`. Each call connects to port
  9222 ad hoc.
- `needs_login` — CLI-internal probe; returns
  `{"status":"ready","needs_login":bool}` based on the sentinel. The CLI
  POSTs this before `start` so it can print "sign in then close the window"
  before the long blocking wait.

## State on disk

- `./user-data/` — full Chrome profile. Created on first Chrome launch.
  **Never delete.** Killing Chrome processes that hold the profile is fine
  and expected; removing the directory is not.
- `./user-data/.wolfie-login-complete` — sentinel touched after the
  first-time-login Chrome window closes. Presence means "a human completed
  login at least once on this profile". `init` deletes it to force re-login.
- `./.wolfie_history` — REPL command history.

## Don't-touch list

- Never delete `./user-data/`.
- Keep the daemon bound to `127.0.0.1` — there is no auth.
- Daemon runs under `fastapi dev` (auto-reload). Editing daemon code does
  not require a manual restart.
- `_ensure_user_data_initialized()` is still called by `init` — leave it
  alone even though `start` no longer uses it.
- Long-running blocking calls (e.g. `proc.wait()` on the login window)
  inside `run_agent_browser_vercel_command` are wrapped in
  `asyncio.to_thread` at the route layer (`agent_browser_command.py`).
  Preserve that wrap if you change the route.

## How to run

```bash
uv tool install -e . --force
wolfie
# at the prompt: start
```

## Static check

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall cli daemon llm_orchestration_langgraph
```
