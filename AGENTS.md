# AGENTS.md

## Project Overview

This repository is an early-stage local browser automation tool named `wolfie`.

At a high level:
- The `wolfie` CLI starts a local FastAPI daemon.
- The daemon manages a Chrome session launched with `--remote-debugging-port=9222`.
- It then runs `agent-browser connect 9222` so an external agent can attach to that browser session.
- Browser profile data is stored in `./user-data` at the repo root.

The README is still a scratchpad. Treat the source code as the current source of truth.

## Main Entrypoints

- CLI entrypoint: `wolfie` via `cli/wolfie/__init__.py`
- Interactive CLI boot: `cli/wolfie/app/app.py`
- Daemon app: `daemon/main.py`
- Browser/session process manager: `daemon/browser/playwright_runner.py`
- HTTP routes:
  - `daemon/router/api.py`
  - `daemon/router/agent_browser_command.py`
- Legacy/direct command adapter:
  - `llm_orchestration_langgraph/functions/agent_browser_vercel.py`

## Current Architecture

### CLI layer

`cli/wolfie/app/app.py` does three things when run without a subcommand:
- ensures runtime dependencies exist
- ensures the daemon is running on `127.0.0.1:8765`
- opens the interactive prompt UI

The prompt UI lives in `cli/wolfie/ui/shell.py`.

### Runtime dependency bootstrap

`cli/wolfie/runtime/node.py`:
- prefers a system `node` if available
- otherwise downloads a bundled Node runtime
- installs `agent-browser` globally into a local prefix under the user home directory

### Daemon layer

`daemon/main.py` mounts:
- `/health`
- `/run-stream`
- `/browser/setup-page`
- `/browser/setup-complete`
- `/browser/stop`
- `/run-agent-browser-vercel-command`

### Browser control

`daemon/browser/playwright_runner.py` is the active browser session manager. It:
- ensures `google-chrome` exists
- ensures `agent-browser` exists
- initializes `./user-data` if missing
- launches Chrome on port `9222`
- waits for the CDP port to come up
- launches `agent-browser connect 9222`
- captures recent `agent-browser` logs in memory

## How To Run

Typical local flow:

```bash
uv tool install -e . --force
wolfie
```

Direct daemon run:

```bash
uv run uvicorn daemon.main:app --host 127.0.0.1 --port 8765
```

Useful endpoints:
- `GET /health`
- `POST /browser/stop`
- `POST /run-agent-browser-vercel-command`

## Important Implementation Notes

- This repo currently has two overlapping command paths:
  - the daemon-first path in `daemon/browser/playwright_runner.py`
  - the direct subprocess path in `llm_orchestration_langgraph/functions/agent_browser_vercel.py`
- The CLI currently posts all shell commands to `/run-agent-browser-vercel-command` from `cli/wolfie/client/stream.py`. The streaming `/run-stream` route exists, but the current CLI path does not use it.
- `playwright` is listed as a dependency, but browser management is currently done through Chrome subprocesses and CDP connection setup, not through Playwright APIs.
- The browser profile is persistent. Be careful with `./user-data`; do not delete it unless explicitly asked.

## Known Rough Edges

- `cli/wolfie/runtime/node.py` hardcodes a Linux Node download URL (`linux-x64`). That will not work as-is on macOS without a system Node already installed.
- `cli/wolfie/runtime/node.py` installs tools under `~/.toolname`, which looks like a placeholder path rather than a finalized project-specific location.
- The README does not document the daemon routes or the split between the newer daemon flow and the legacy direct command flow.
- There are no tests in the repository today.

## Working Conventions For Agents

- Prefer reading the code over relying on the README.
- Preserve the current local-first workflow: CLI -> daemon -> Chrome remote debugging -> `agent-browser connect`.
- If changing browser startup behavior, check both active code paths so they do not drift further apart unless the task is explicitly to remove one.
- Avoid destructive operations against `./user-data` unless the user explicitly asks.
- Keep changes small and practical; this codebase is still in a prototyping phase.

## Suggested Validation

Because this project depends on local binaries and networking, validation should usually be incremental:

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall cli daemon llm_orchestration_langgraph
```

If dependencies are available locally:

```bash
uv run uvicorn daemon.main:app --host 127.0.0.1 --port 8765
```

Then verify:
- `GET /health` returns `{"status":"ok"}`
- `wolfie` starts the prompt
- `start` launches Chrome on port `9222`

