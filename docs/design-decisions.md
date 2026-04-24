# Wolfie — Design Decisions

This document records the "why" behind the current shape of the code. Each
entry is a decision that was actually made (readable in the code or the
commit history), not a proposal. Where a decision looks temporary or wrong,
that is called out explicitly.

## 1. CLI and daemon are separate processes

**Decision.** The `wolfie` CLI is a Typer app. Work that touches the
browser is done by a FastAPI daemon on `127.0.0.1:8765`. The CLI talks to
the daemon over HTTP.

**Why.**
- The browser session is **long-lived**; the REPL is not. Splitting them
  lets the user `exit` the CLI without killing Chrome or `agent-browser`.
- A daemon is the natural place for future concurrent work (multiple
  agents, streaming tool output, watchdogs). The CLI stays a thin client.
- A daemon gives a stable HTTP surface that things other than the REPL
  (e.g. a future desktop UI, a hotkey launcher, another agent) can drive.

**Trade-off.**
- Two processes means more moving parts for a prototype. The CLI has to
  bootstrap the daemon (`ensure_daemon`), which adds a 15-second worst-case
  startup penalty on a cold start.
- Shared state lives in the daemon, which means CLI restarts lose REPL
  context but not browser context. That is the desired asymmetry.

## 2. Daemon binds only to loopback, no auth

**Decision.** FastAPI is started with `--host 127.0.0.1`, and the daemon
has no authentication middleware.

**Why.** The threat model is a single developer on their own laptop. Adding
auth to a localhost-only daemon would be ceremony without benefit.

**Trade-off.** If anyone ever runs the daemon on `0.0.0.0` or behind a
reverse proxy, `POST /run-agent-browser-vercel-command` becomes RCE. This
is acceptable for a prototype but must be revisited before any packaging
story.

## 3. One HTTP endpoint carries all commands

**Decision.** `POST /run-agent-browser-vercel-command` takes
`{"command": "<freeform string>"}` and `shlex.split`s it inside the daemon.

**Why.**
- The REPL is the primary user interface. It already produces freeform
  strings. Mirroring that shape avoids designing a command schema
  prematurely while the verb set (`start`, `open`) is still churning.
- It matches how `agent-browser` itself is driven — by command lines — so
  the mapping is near-identity.

**Trade-off.**
- No typed API. Adding a new command means editing a string dispatch in
  `run_agent_browser_vercel_command`.
- Callers other than the REPL have to know the command grammar.

**When to revisit.** As soon as a second, non-REPL caller needs to drive
the daemon. At that point give each verb its own route with a typed body.

## 4. Chrome is managed via raw subprocess and CDP, not Playwright

**Decision.** `agent_browser_vercel.py` starts Chrome with
`subprocess.Popen`, polls the CDP port on a plain TCP socket, and hands
off the port number to `agent-browser`.

**Why.**
- The goal is to hand a **pre-authenticated Chrome** to an agent that
  already knows how to speak CDP. Playwright would add a layer Wolfie
  would immediately have to get out of `agent-browser`'s way.
- Everything Wolfie needs to know is "is port 9222 accepting TCP yet?"
  A socket `connect_ex` is enough. Full CDP handshaking is not needed.

**Trade-off.**
- `playwright` is still a dependency in `pyproject.toml` from an earlier
  spike. It should be removed to avoid confusing future readers.
- Polling a socket does not confirm Chrome is fully responsive, only that
  the port is open. The retry-once fallback papers over the rare case
  where Chrome accepts the socket but is not actually ready.

## 5. Profile persistence is the core UX contract

**Decision.** Chrome is always launched with `--user-data-dir=./user-data`.
`_terminate_existing_chrome_with_profile()` SIGTERM/SIGKILLs any other
Chrome on that profile before relaunching.

**Why.** Chrome refuses to open a profile that is already locked by
another process. Without eager termination, `start` would fail whenever
the user had the browser open from last time. The entire point of the
tool is "agent attaches to my signed-in browser," so the profile has to
be treated as a shared, single-owner resource.

**Trade-off.**
- Killing Chrome outside the profile (other Chrome windows on other
  profiles) is avoided because the `pgrep` pattern includes the full
  profile path. This is the reason that check is profile-scoped and not
  process-name-scoped. Do not simplify it.
- Any unsaved form data in that Chrome window is lost on `start`. That
  is accepted: `start` is defined as "take this browser over."

## 6. First-run profile initialization uses a disposable Chrome window

**Decision.** If `./user-data` does not exist, launch Chrome once with a
`data:` URL containing JavaScript that calls `window.close()` after
700 ms. Wait for that process to exit, then proceed.

**Why.** Chrome will not create a profile directory in a single-instant
invocation. It has to actually boot the profile. A disposable window is
the least intrusive way to force that without asking the user to log in
during bootstrap.

**Trade-off.**
- 700 ms is hand-tuned. On a very slow machine it might fire before the
  profile is fully written. If that becomes a real problem, watch for
  `./user-data/Default/` instead of sleeping.
- The `data:` URL script depends on Chrome allowing `window.close()` on
  a tab it opened via command line. This works today on Chrome; it is
  not a portable guarantee.

## 7. `agent-browser` is installed into a local npm prefix, not globally

**Decision.** `runtime/node.py` runs `npm install -g agent-browser
--prefix ~/.toolname/npm-global` and adds that prefix's `bin` to the
subprocess PATH.

**Why.**
- Avoids requiring `sudo` or polluting the user's global npm.
- Makes the install reproducible and cleanly removable: delete
  `~/.toolname`, everything is gone.

**Trade-off.**
- The directory name `~/.toolname` is a placeholder. It should be
  `~/.wolfie` before this is shipped to anyone.
- PATH manipulation only happens for subprocesses the daemon spawns. The
  user's interactive shell does not get `agent-browser` on its PATH. That
  is deliberate — Wolfie is the one that runs `agent-browser`, not the
  user.

## 8. Node bootstrap prefers system Node, falls back to bundled

**Decision.** `ensure_node()` checks for a system `node` first, uses it
if present, and only downloads Node if none is found.

**Why.** A download path makes the tool work on a clean machine. A
system-first path makes the tool fast and version-respecting on a
developer's machine.

**Trade-off (active bug).** The download URL is hardcoded to
`linux-x64`. On macOS with no system Node the fallback installs a Linux
binary that cannot execute. This only matters if system Node is missing,
which is why it has not bitten us yet. Proper fix: detect
`sys.platform` and `platform.machine()` and pick the matching archive.

## 9. The daemon is started with `fastapi dev` (auto-reload)

**Decision.** `ensure_daemon` spawns
`uv run fastapi dev daemon/main.py`.

**Why.** During active development this means code edits to the daemon
take effect without the human restarting anything. Given the daemon is a
persistent background process the user forgets about, auto-reload is the
difference between "edit and keep working" and "every change requires a
pkill."

**Trade-off.**
- `fastapi dev` is not intended for packaged distribution. When this
  project is shipped, swap to `uvicorn daemon.main:app` and drop the
  reload loop.
- Auto-reload watchers can interact badly with subprocess lifetimes. If
  Chrome is ever launched as a *child* of a uvicorn worker (it is not
  today; `subprocess.Popen` detaches it), reloads would kill the browser.

## 10. Command dispatch lives in `llm_orchestration_langgraph/`

**Decision.** The file that actually launches Chrome is
`llm_orchestration_langgraph/functions/agent_browser_vercel.py`.

**Why (historical).** The folder name anticipates a future where command
handling is a LangGraph-orchestrated pipeline (intent parsing, tool
selection, side effects, observation, follow-up). Keeping today's direct
subprocess logic inside that folder means future refactors land where
the code already lives.

**Trade-off.** Today it is misleading: there is no LangGraph, no LLM, no
orchestration. A reader looking for the browser logic would not expect
it there. The AGENTS.md file already warns about this; the folder should
be renamed (`orchestration/`) once a second caller exists.

## 11. Chrome discovery is PATH-based (and currently Linux-shaped)

**Decision.** `_ensure_chrome_installed()` uses `shutil.which(...)` across
a small candidate list (`google-chrome`, the macOS `.app` bundle path,
`/usr/bin/google-chrome`).

**Why.** Keeps discovery trivial. No user configuration, no env var, no
registry lookup. Works on any Linux distro that installs Chrome the
standard way and on stock macOS.

**Trade-off.**
- Windows is not supported.
- Chromium, Brave, Edge, and other Chromium-family browsers are not
  auto-detected, even though they would work. If a user wants one of
  those, the candidate list is the place to extend.

## 12. No tests

**Decision.** There is no test suite and no CI wiring.

**Why.** Almost every meaningful behavior in this project is an
interaction with a real Chrome binary, a real npm registry, or a real
operating system. Mocking those would test the mocks, not the tool.
Until the project has a stable command surface worth pinning, tests are
a liability.

**Trade-off.** Regressions are caught by running `wolfie` manually. That
is fine for one user. Before any external contributor lands a PR, there
needs to be at least a smoke test that boots the daemon and hits
`/health`.

## 13. `user-data/` is gitignored and treated as sacred

**Decision.** `./user-data` is in `.gitignore`. Code never deletes it.
The termination routine kills Chrome *processes* using the profile, not
the profile itself.

**Why.** The profile contains the user's logged-in sessions. Losing it
means every site has to be re-authenticated, which defeats the entire
premise of Wolfie. This is the most important piece of state in the
repo.

**Trade-off.** None worth discussing. Do not break this.

---

## Decisions that should be revisited soon

These are not decisions to defend; they are live debts.

- **Rename `~/.toolname`** to `~/.wolfie`.
- **Rename `llm_orchestration_langgraph/`** to something honest
  (`orchestration/` or fold it into `daemon/`).
- **Delete `playwright` from `pyproject.toml`** if no code is going to
  use it. Right now it only slows installs and misleads readers.
- **Fix the Linux-only Node download URL.**
- **Give each REPL verb its own typed endpoint** once a second,
  non-REPL caller appears.
- **Sync AGENTS.md with reality** — it still describes
  `daemon/browser/playwright_runner.py` and routes that no longer exist.
