# Wolfie

Wolfie is a local browser automation project that lets an AI agent control a
real Chrome window using a persistent browser profile.

I built it because most browser agents are designed around clean, headless, or
temporary browser sessions. That is useful for tests, but it breaks down for
real personal workflows. The sites I actually want an agent to use are usually
behind logins, cookies, saved sessions, two-factor checks, Google auth, and
browser state that already exists on my machine.

Wolfie takes the opposite approach: keep the browser local, keep the profile
persistent, and let the agent attach to the same Chrome session that I can see
and use myself.

## Demo

Demo video coming soon.

<!-- Replace this section with an embedded video or link after upload. -->

## What Wolfie Does

Wolfie starts a local CLI and daemon that manage a Chrome session for browser
automation.

At a high level:

1. Wolfie creates or reuses a persistent Chrome profile in `./user-data`.
2. It launches Chrome with remote debugging enabled on port `9222`.
3. It connects the external `agent-browser` CLI to that Chrome session.
4. It exposes a local REPL where I can start the browser, open URLs, and send
   high-level browser tasks to an agent.
5. The daemon runs a planner/executor loop that uses Gemini to decide browser
   actions and `agent-browser` to execute them.

The result is a headed browser agent that can operate inside my real logged-in
browser state instead of a blank disposable environment.

## Why This Exists

Most browser automation agents have one or more of these problems:

- They run headless, so the human cannot comfortably watch or intervene.
- They start from a clean profile, so every authenticated site becomes a setup
  problem.
- They do not preserve cookies, sessions, extensions, or browser state.
- They feel detached from the actual browser I use every day.

Wolfie is an experiment in making agentic browser automation feel local-first.
The agent does not get a fake browser. It gets the same Chrome profile I logged
into.

That makes it much more practical for workflows like:

- Using Gmail or other logged-in web apps.
- Navigating sites that depend on saved sessions.
- Reusing Google auth or other existing login state.
- Watching the agent work in a visible browser window.
- Taking over manually when needed.

## Architecture

Wolfie has three main pieces:

| Component | Role |
| --- | --- |
| `wolfie` CLI | Interactive terminal interface for starting the browser and sending tasks |
| FastAPI daemon | Local service on `127.0.0.1:8765` that owns browser and agent state |
| `agent-browser` | External CLI tool that talks to Chrome through CDP |

Chrome is the shared surface between the user and the agent.

```text
user
  |
  v
wolfie CLI
  |
  | HTTP on 127.0.0.1:8765
  v
FastAPI daemon
  |
  | launches Chrome with --remote-debugging-port=9222
  v
Chrome using ./user-data
  ^
  |
  | CDP on 127.0.0.1:9222
  |
agent-browser
```

The daemon stays local. It is not designed to be exposed to the network.

## Technical Flow

When I run `wolfie`, the CLI:

1. Checks runtime dependencies.
2. Starts the FastAPI daemon if it is not already running.
3. Opens an interactive shell.

When I type `start`, the daemon:

1. Resolves a Chrome executable.
2. Initializes `./user-data` if the profile does not exist yet.
3. Terminates any existing Chrome process using that same profile.
4. Launches Chrome with:

```bash
--remote-debugging-port=9222
--user-data-dir=./user-data
--no-first-run
--no-default-browser-check
```

5. Waits for the Chrome DevTools Protocol port to become available.
6. Runs:

```bash
agent-browser connect 9222
```

When I type `prompt <task>`, the daemon runs a LangGraph planner/executor loop:

- The planner owns the user goal, plan, stopping condition, and course
  correction.
- The executor receives one outcome-based task at a time.
- The executor selects `agent-browser` commands such as `snapshot`, `click`,
  `fill`, `press`, `get url`, and `screenshot`.
- After state-changing actions, Wolfie runs validation commands so the agent has
  evidence of what changed.
- If the agent needs human input, it pauses and asks me to reply with
  `input <answer>`.

## Commands

Inside the Wolfie shell:

| Command | Description |
| --- | --- |
| `start` | Launch Chrome with the persistent profile and connect `agent-browser` |
| `init` | Open the persistent profile for login or setup |
| `open <url>` | Open a URL using the persistent profile |
| `prompt <task>` | Ask the browser agent to perform a task |
| `input <answer>` | Reply when the agent asks for clarification or approval |
| `state` | Show the current agent session state |
| `help` | Show CLI help |
| `clear` | Clear the shell |
| `exit` / `quit` | Exit the REPL without killing Chrome or the daemon |

## Setup

Install the CLI in editable mode:

```bash
uv tool install -e . --force
```

Run Wolfie:

```bash
wolfie
```

Then start the browser session:

```text
wolfie > start
```

For agent prompts, set a Gemini API key:

```bash
cp .env.local.example .env.local
```

Then edit `.env.local`:

```bash
GEMINI_API_KEY="your-gemini-api-key"
WOLFIE_GEMINI_MODEL="gemini-flash-latest"
```

Run Wolfie again after changing environment settings.

## Example

```text
wolfie > start
wolfie > open https://mail.google.com
wolfie > prompt draft a short introduction email to someone and ask me before sending
```

If the agent needs more information, it will ask for it:

```text
wolfie > input send it to example@example.com and keep the tone casual
```

## Project Layout

```text
cli/wolfie/
  app/app.py                 CLI entrypoint
  ui/shell.py                Interactive REPL
  client/daemon.py           CLI to daemon HTTP client and stream renderer
  runtime/daemon.py          Starts the local FastAPI daemon
  runtime/node.py            Ensures Node and agent-browser are available

daemon/
  main.py                    FastAPI app setup
  router/api.py              Health route
  router/agent_browser_command.py
                             Browser startup and passthrough command route
  router/agent.py            Agent prompt, input, and state routes
  agent/graph.py             LangGraph planner/executor loop
  agent/prompts.py           Planner and executor prompts
  agent/tools.py             agent_browser(command) tool wrapper
  agent/sessions.py          In-memory task session state

llm_orchestration_langgraph/functions/
  agent_browser_vercel.py    Chrome startup, profile handling, CDP checks,
                             and agent-browser process spawning
```

## Local State

Wolfie writes local state to:

| Path | Purpose |
| --- | --- |
| `./user-data/` | Persistent Chrome profile with cookies, sessions, and browser data |
| `./.wolfie_history` | REPL history |
| `~/.toolname/npm-global/` | Local npm prefix used for `agent-browser` |

Do not delete `./user-data` unless you intentionally want to remove the saved
browser profile.

## Security Notes

Wolfie is a local prototype.

- The daemon binds to `127.0.0.1`.
- There is no authentication layer on the daemon.
- Do not bind it to `0.0.0.0`.
- The Chrome profile can contain real logged-in sessions.
- Treat `./user-data` as sensitive local data.
- Agent actions happen in the same browser identity that the user uses.

This project is built for single-user local experimentation, not for hosting as
a remote service.

## Current Status

Wolfie is an early prototype. The main idea works: a local CLI can launch a
persistent Chrome profile, connect `agent-browser`, and run a Gemini-backed
planner/executor loop against that visible browser session.

The code still has rough edges, including local dependency bootstrapping,
limited tests, and prototype naming in a few folders. The source code is the
best reference for current behavior.
