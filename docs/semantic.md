# Wolfie — Semantic Overview

## What this project is

Wolfie is a local, single-user tool that lets an AI browser-automation agent
(`agent-browser`, an external npm package) drive a real Chrome window that the
human has already signed into.

It exists to answer one practical question:

> *"How do I let an agent operate my browser, using my sessions and cookies,
> without handing it my passwords or running everything in a sandboxed
> headless browser that has no idea who I am?"*

The answer Wolfie implements:

1. The human launches a normal Chrome with a **persistent profile directory**
   (`./user-data`) and logs into whatever sites they want.
2. Later, Wolfie relaunches that same Chrome with **remote debugging enabled**
   (CDP on port `9222`).
3. Wolfie attaches `agent-browser` to that CDP endpoint.
4. From then on, the agent and the human share the same browser session.

Wolfie itself is not the agent. Wolfie is the plumbing that makes the agent's
connection to a real signed-in browser boring and repeatable.

## The three actors

| Actor            | What it is                                           | Who runs it            |
|------------------|------------------------------------------------------|------------------------|
| `wolfie` CLI     | Interactive shell the user types into                | User                   |
| Wolfie daemon    | Local FastAPI service on `127.0.0.1:8765`            | Auto-started by CLI    |
| `agent-browser`  | External npm tool that speaks to Chrome via CDP      | Spawned by the daemon  |

Chrome is the shared surface. Both the human and `agent-browser` act on the
same Chrome process.

## The mental model in one picture

```
 ┌──────────┐   HTTP     ┌────────────┐   subprocess   ┌────────────────┐
 │  wolfie  │ ─────────▶ │  daemon    │ ─────────────▶ │ google-chrome  │
 │  (CLI)   │  :8765     │  FastAPI   │   CDP :9222    │  + user-data   │
 └──────────┘            └────────────┘                └────────────────┘
       │                       │                              ▲
       │                       │ subprocess                   │
       │                       ▼                              │
       │                ┌───────────────┐   CDP :9222         │
       │                │ agent-browser │ ────────────────────┘
       │                │   connect     │
       │                └───────────────┘
       ▼
   user types
   "start", "open <url>", "exit"
```

Everything happens on `localhost`. Nothing in this project is designed to be
exposed to the network.

## What lives where (ground truth, as of current code)

```
cli/wolfie/
  app/app.py              Typer entrypoint; boots runtime deps, daemon, shell
  ui/shell.py             prompt_toolkit REPL, writes .wolfie_history
  ui/runtime_messages.py  Rich console banners for startup
  client/stream.py        Sends every typed line to the daemon via httpx
  core/config.py          Typer app, Rich console, daemon URLs, completer
  runtime/daemon.py       Starts the FastAPI daemon if not already healthy
  runtime/node.py         Ensures Node + installs agent-browser via npm

daemon/
  main.py                          FastAPI app wiring
  middlewares/request_context.py   Adds X-App-Name response header
  router/api.py                    GET /health
  router/agent_browser_command.py  POST /run-agent-browser-vercel-command

llm_orchestration_langgraph/
  functions/agent_browser_vercel.py
      The actual "do the thing" module: launches Chrome, manages the
      user-data profile, waits for CDP, spawns `agent-browser connect`.
```

Despite the directory name `llm_orchestration_langgraph`, there is no
LangGraph code here today. The name is a placeholder for where orchestration
logic is meant to grow.

## The user-facing commands (inside the REPL)

Typed into the `wolfie ❯` prompt. Each line is POSTed to the daemon as
`{"command": "<text>"}` against `/run-agent-browser-vercel-command`.

| Command         | What the daemon does                                              |
|-----------------|-------------------------------------------------------------------|
| `start`         | Initialize `./user-data` if missing, kill any Chrome on that profile, launch Chrome with `--remote-debugging-port=9222`, wait for CDP, spawn `agent-browser connect 9222` |
| `open <url>`    | Launch Chrome on the profile pointed at that URL (no remote debugging) |
| `exit` / `quit` | CLI-side only: ends the REPL. Does not stop the daemon or Chrome. |

An optional `agent-browser` prefix is tolerated (e.g. `agent-browser start`
equals `start`). Any other verb returns `unsupported_command`.

## HTTP surface of the daemon

| Method | Path                                    | Purpose                  |
|--------|-----------------------------------------|--------------------------|
| GET    | `/health`                               | Liveness, used by CLI    |
| POST   | `/run-agent-browser-vercel-command`     | Run a REPL command       |

Nothing else. Anything else referenced in older docs (`/run-stream`,
`/browser/setup-page`, `/browser/stop`) does not exist in the current tree.

## Startup, end to end

When the user runs `wolfie`:

1. `ensure_runtime_dependencies()` — confirm a system `node` exists (or
   download one into `~/.toolname`), then `npm install -g agent-browser`
   into a local prefix so the binary is on `PATH`.
2. `ensure_daemon()` — hit `GET /health`. If it fails, spawn
   `uv run fastapi dev daemon/main.py --host 127.0.0.1 --port 8765`
   in the background and poll for up to 15 seconds.
3. `interactive_shell()` — open a `prompt_toolkit` REPL with history at
   `.wolfie_history` and a completer for `start`, `open`, `exit`, `quit`.

When the user types `start`:

1. CLI POSTs to the daemon.
2. Daemon calls `run_agent_browser_vercel_command("start")`.
3. `_ensure_chrome_installed()` resolves a Chrome executable.
4. `_ensure_user_data_initialized()` creates `./user-data` on first run by
   briefly launching Chrome with an auto-closing `data:` URL.
5. `_terminate_existing_chrome_with_profile()` SIGTERMs (then SIGKILLs)
   any Chrome already holding that profile — Chrome refuses to open a
   profile that is already locked.
6. Chrome is launched with `--remote-debugging-port=9222
   --no-first-run --no-default-browser-check`.
7. `_wait_for_cdp_ready()` polls `127.0.0.1:9222` for up to 12 s. If it
   fails the first time, the flow retries once.
8. `agent-browser connect 9222` is spawned as a detached subprocess.
9. JSON `{status, pid, agent_connect_pid, executed}` is returned to the CLI,
   which prints it verbatim.

## State on disk

| Path                       | What it is                                              |
|----------------------------|---------------------------------------------------------|
| `./user-data/`             | Chrome profile (cookies, logins, extensions). Persistent. Do not delete. |
| `./.wolfie_history`        | `prompt_toolkit` REPL history                           |
| `~/.toolname/node/`        | Bundled Node, only populated if no system Node exists   |
| `~/.toolname/npm-global/`  | `agent-browser` install prefix                          |
| `./.venv`, `./.uv-cache`   | uv-managed Python environment                           |

## What Wolfie deliberately is not

- **Not a browser automation framework.** It does not drive the browser
  itself. Playwright is in `pyproject.toml` but is unused today; it is a
  leftover from an earlier spike.
- **Not a multi-user / multi-session service.** One user, one profile, one
  Chrome, one port. No auth on the daemon because the daemon binds only to
  loopback.
- **Not a production deployment target.** The daemon is started with
  `fastapi dev` (auto-reload on file changes), which is intentional for this
  prototyping phase.
- **Not cross-user agent orchestration.** The `llm_orchestration_langgraph`
  folder name is aspirational. Nothing in the current code uses LangGraph,
  LLMs, or orchestration graphs.

## Current maturity

Prototype. Features land by moving fast in one file
(`agent_browser_vercel.py`) and hanging the daemon and CLI off that. The
commit history (`cli and daemon code initialization`, `clean up`,
`new start up command`) shows the shape is still being discovered, not
stabilized. Treat every interface in this repo as provisional.
