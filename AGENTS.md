# AGENTS.md

## Project Overview

This repository is an early-stage local browser automation tool named `wolfie`.

At a high level:
- The `wolfie` CLI starts a local FastAPI daemon on `127.0.0.1:8765`.
- The daemon manages a Chrome session launched with `--remote-debugging-port=9222`.
- It then runs `agent-browser connect 9222` so an external agent can attach to that browser session.
- Browser profile data is stored in `./user-data` at the repo root.

The top-level `README.md` is still a scratchpad. For a grounded overview,
read `docs/semantic.md` and `docs/design-decisions.md`. Treat the source
code as the ultimate source of truth.

## Main Entrypoints

- CLI entrypoint: `wolfie` via `cli/wolfie/__init__.py` → `cli/wolfie/app/app.py`
- Interactive REPL: `cli/wolfie/ui/shell.py`
- CLI → daemon transport and response rendering: `cli/wolfie/client/daemon.py`
- Shared CLI styling: `cli/wolfie/ui/theme.py`
- Runtime dependency bootstrap: `cli/wolfie/runtime/node.py`, `cli/wolfie/runtime/daemon.py`
- Daemon app: `daemon/main.py`
- HTTP routes:
  - `daemon/router/api.py` — `GET /health`
  - `daemon/router/agent_browser_command.py` — `POST /run-agent-browser-vercel-command`
  - `daemon/router/agent.py` — `POST /agent/prompt`
- Daemon LangGraph agent layer:
  - `daemon/agent/graph.py` — planner/executor loop
  - `daemon/agent/prompts.py` — system prompt and role prompts
  - `daemon/agent/tools.py` — `agent_browser(command)` tool wrapper
  - `daemon/agent/service.py` — streams graph events as NDJSON
- Command dispatcher (launches Chrome, spawns `agent-browser`):
  - `llm_orchestration_langgraph/functions/agent_browser_vercel.py`

## Current Architecture

### CLI layer

`cli/wolfie/app/app.py` does three things when run without a subcommand:
- ensures runtime dependencies exist (`ensure_runtime_dependencies`)
- ensures the daemon is running on `127.0.0.1:8765` (`ensure_daemon`)
- opens the interactive REPL (`interactive_shell`)

The REPL lives in `cli/wolfie/ui/shell.py`. Local shell commands
(`help`, `clear`, `exit`, `quit`) are handled in-process. Every other typed
line is POSTed to the daemon's `/run-agent-browser-vercel-command` endpoint
via `cli/wolfie/client/daemon.py`. The CLI is otherwise stateless — REPL
history is persisted to `./.wolfie_history`.

The public help/completer intentionally exposes only `start`, `init`,
`open <url>`, `prompt <task>`, `help`, `clear`, `exit`, and `quit`. Do not add
`agent ...` commands back to the public help unless the product surface
changes. `agent-browser ...` may still be accepted as an undocumented
manual-testing passthrough while prototyping, but it should remain hidden from
normal CLI help and completion.

### Runtime dependency bootstrap

`cli/wolfie/runtime/node.py`:
- prefers a system `node` if available
- otherwise downloads a bundled Node runtime (currently Linux-only; see
  "Known Rough Edges")
- checks for `agent-browser`, logs the detected binary/version when present,
  and installs it with npm into `~/.toolname/npm-global` when missing
- exposes a `runtime_env()` helper that injects that prefix's `bin/` into
  `PATH` for subprocesses

`cli/wolfie/runtime/daemon.py`:
- polls `GET /health`
- if unhealthy, spawns `uv run fastapi dev daemon/main.py --host 127.0.0.1 --port 8765`
- waits up to ~15 seconds for health

### Daemon layer

`daemon/main.py` mounts these routes:
- `GET  /health` — liveness, returns `{"status":"ok"}`
- `POST /run-agent-browser-vercel-command` — accepts `{"command": "<string>"}`
  and dispatches to `run_agent_browser_vercel_command`
- `POST /agent/prompt` — accepts `{"prompt": "<task>", "thread_id": "...",
  "max_steps": 20}` and streams NDJSON agent events back to the CLI

Middleware in `daemon/middlewares/request_context.py` adds an
`X-App-Name: workwolf-daemon` response header.

### LangGraph agent layer

The LangGraph agent is daemon-owned. The CLI only submits a prompt and renders
streamed events; it must not contain planner, executor, model, or browser-tool
logic.

The graph is a planner/executor correction loop:
- planner/controller owns the user goal, plan, next task, stopping condition,
  and course correction when observations do not match expectations
- executor receives exactly one narrow task, chooses one `agent-browser`
  command, runs it, and returns an observation
- the loop continues until the planner marks the task done, asks the user,
  fails, or hits `max_steps`

The only browser tool exposed to the executor is
`agent_browser(command: str)`, implemented in `daemon/agent/tools.py`. It uses
the existing `agent-browser` CLI wrapper in
`llm_orchestration_langgraph/functions/agent_browser_vercel.py`, so it runs
against the same headed Chrome profile connected on CDP port `9222`.
Before invoking the graph, `daemon/agent/service.py` preflights
`agent-browser connect 9222`; if CDP is not ready, the stream tells the user
to run `start` first.

Gemini is accessed through `google-genai`; the default model is
`gemini-3-pro-preview` and can be overridden with `WOLFIE_GEMINI_MODEL`.
The default thinking level is `HIGH` and can be overridden with
`WOLFIE_GEMINI_THINKING_LEVEL`.

### Browser / command dispatch

`llm_orchestration_langgraph/functions/agent_browser_vercel.py` is the
single module that actually drives Chrome. It:
- resolves a Chrome executable across Linux and macOS candidate paths
- on first run, creates `./user-data` by launching Chrome once with an
  auto-closing `data:` URL
- kills any existing Chrome holding the profile (matched by
  `--user-data-dir=...` in the process command line)
- launches Chrome with `--remote-debugging-port=9222 --no-first-run
  --no-default-browser-check`
- waits for CDP by `connect_ex` on `127.0.0.1:9222` (up to 12 s, retries once)
- spawns `agent-browser connect 9222` as a detached subprocess
- returns `{status, pid, agent_connect_pid, executed}` as JSON

Supported verbs inside the REPL:
- `start` — full bring-up described above
- `init` — open the persistent profile for login / re-login setup
- `open <url>` — launch Chrome on the profile pointed at a URL (no CDP)
- `prompt <task>` — send a task to the daemon LangGraph browser agent
- `help` — CLI-only, shows the public command list
- `clear` — CLI-only, clears the terminal and redraws the shell header
- `exit` / `quit` — CLI-only, ends the REPL; does not stop the daemon or Chrome

The CLI forwards non-local commands to the daemon even if they are not listed
in help. Keep testing-only passthroughs undocumented unless they become part
of the real user workflow.

## How To Run

Typical local flow:

```bash
uv tool install -e . --force
wolfie
# then at the prompt:
#   start
```

Direct daemon run (bypasses the CLI):

```bash
uv run fastapi dev daemon/main.py --host 127.0.0.1 --port 8765
```

Quick HTTP sanity check:

```bash
curl http://127.0.0.1:8765/health
curl -X POST http://127.0.0.1:8765/run-agent-browser-vercel-command \
     -H 'Content-Type: application/json' \
     -d '{"command":"start"}'
```

## Important Implementation Notes

- **Single command path.** There is now only one path for handling REPL
  commands: `agent_browser_vercel.py`. An older `daemon/browser/playwright_runner.py`
  was removed in the "clean up" commit (`7e1cf5b`). Do not reintroduce a
  parallel path without a concrete reason.
- **`playwright` is an unused dependency.** It is listed in `pyproject.toml`
  from an earlier spike. Browser management is done with raw `subprocess`
  + a TCP poll of the CDP port, not via Playwright APIs.
- **The daemon runs under `fastapi dev`**, which auto-reloads on file
  changes. Editing daemon code does *not* require a manual restart.
- **The browser profile is persistent and precious.** `./user-data` holds
  logged-in sessions. Never delete it. The termination routine kills
  *processes* using the profile, not the directory.
- **`llm_orchestration_langgraph/` is an aspirational folder name.** There
  is no LangGraph, no LLM, no orchestration graph in that code today — just
  subprocess plumbing. Rename is pending.

## Known Rough Edges

- `cli/wolfie/runtime/node.py` hardcodes a Linux Node download URL
  (`linux-x64`). On macOS without a system Node, the fallback will fetch a
  Linux binary that cannot execute. System Node is preferred, so this only
  bites on a genuinely clean machine.
- `cli/wolfie/runtime/node.py` installs tools under `~/.toolname`, which
  is a placeholder path. Should be `~/.wolfie`.
- `playwright` is still in `pyproject.toml` despite being unused.
- There are no tests and no CI.
- The top-level `README.md` is a personal scratchpad, not documentation.

## Working Conventions For Agents

- Prefer reading the code over relying on the top-level README. Prefer
  `docs/semantic.md` and `docs/design-decisions.md` over this file when
  they conflict — they are intended to stay closer to the code.
- Preserve the current local-first workflow: CLI → daemon → Chrome remote
  debugging → `agent-browser connect`.
- Keep the daemon bound to `127.0.0.1`. There is no auth; binding to
  anything else is a remote-code-execution hazard.
- Avoid destructive operations against `./user-data` unless the user
  explicitly asks. Killing Chrome processes that hold the profile is fine
  and expected; removing the profile directory is not.
- Keep changes small and practical; this codebase is still prototyping.
  Do not add frameworks, abstractions, or parallel code paths on spec.
- When changing Chrome discovery or startup, update
  `_ensure_chrome_installed` and `_ensure_user_data_initialized` together
  — they both need to resolve the same executable.

## Suggested Validation

Because this project depends on local binaries and networking, validation
is incremental and mostly manual.

Static check (no runtime required):

```bash
PYTHONPYCACHEPREFIX=.pycache python3 -m compileall cli daemon llm_orchestration_langgraph
```

Daemon smoke test:

```bash
uv run fastapi dev daemon/main.py --host 127.0.0.1 --port 8765
# in another shell:
curl http://127.0.0.1:8765/health   # expect {"status":"ok"}
```

End-to-end:
- `wolfie` starts the prompt without errors
- `start` launches Chrome on port `9222` and returns
  `{"status":"started", ...}` instead of `chrome_not_found` or `cdp_not_ready`
- A subsequent `open https://example.com` opens a window using the same
  persisted profile
