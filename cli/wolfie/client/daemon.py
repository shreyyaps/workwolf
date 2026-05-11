import asyncio
import json
import os
import time
from collections.abc import Mapping

import httpx
from rich.markup import escape
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..core.config import (
    DAEMON_AGENT_BROWSER_COMMAND_URL,
    DAEMON_AGENT_INPUT_URL,
    DAEMON_AGENT_PROMPT_URL,
    DAEMON_AGENT_STATE_URL,
    console,
)
from ..ui.theme import BG, DIM

STATUS_THEME = {
    "started": ("green", "Started"),
    "ready": ("green", "Ready"),
    "success": ("green", "Success"),
    "awaiting_login": ("yellow", "Waiting For Login"),
    "ignored": ("yellow", "Ignored"),
    "error": ("red", "Error"),
}

DETAIL_KEYS = (
    "pid",
    "agent_connect_pid",
    "debug_port",
    "executed",
    "received",
    "reason",
)


def _format_logs(logs: list) -> None:
    if not logs:
        return

    table = Table.grid(padding=(0, 1))
    table.style = BG
    table.add_column(no_wrap=True)
    table.add_column()

    for log in logs:
        level = log.get("level", "info")
        message = log.get("message", "")

        if level == "success":
            marker = "[green on grey11]OK[/]"
            style = "green"
        elif level == "error":
            marker = "[red on grey11]ERR[/]"
            style = "red"
        elif level == "warning":
            marker = "[yellow on grey11]WARN[/]"
            style = "yellow"
        else:
            marker = "[cyan on grey11]INFO[/]"
            style = "cyan"
        table.add_row(marker, f"[{style} on grey11]{escape(str(message))}[/]")

    console.print()
    console.print(f"[{DIM}]runtime[/]")
    console.print(table)


def _normalize_payload(data: object) -> object:
    if isinstance(data, Mapping) and set(data.keys()) == {"detail"}:
        return data["detail"]
    return data


def _details_table(data: Mapping[str, object]) -> Table | None:
    rows: list[tuple[str, object]] = []

    for key in DETAIL_KEYS:
        value = data.get(key)
        if value not in (None, "", [], {}):
            rows.append((key, value))

    hidden_keys = {
        "status",
        "message",
        "error",
        "hint",
        "logs",
        "data",
        "detail",
        *DETAIL_KEYS,
    }
    for key in sorted(k for k in data if k not in hidden_keys):
        value = data.get(key)
        if value not in (None, "", [], {}):
            rows.append((key, value))

    if not rows:
        return None

    table = Table.grid(padding=(0, 2))
    table.style = BG
    table.add_column(style=DIM, justify="right", no_wrap=True)
    table.add_column(style=f"white {BG}")
    for key, value in rows:
        table.add_row(key.replace("_", " "), Text(str(value)))
    return table


def _print_status(
    title: str,
    body: Text,
    border_style: str,
    elapsed_seconds: float | None = None,
) -> None:
    heading = Text("> ", style=DIM)
    heading.append(title.upper(), style=f"bold {border_style} {BG}")
    if elapsed_seconds is not None:
        heading.append(f" {elapsed_seconds:.1f}s", style=DIM)

    content = Table.grid(padding=(0, 1))
    content.style = BG
    content.add_column(width=2)
    content.add_column()
    content.add_row("", body)

    console.print()
    console.print(heading)
    console.print(content)


def _message_for_status(data: Mapping[str, object], status: str) -> str:
    if status == "started":
        return str(data.get("message") or "Browser started successfully")
    if status == "ready":
        return str(data.get("message") or "Ready for commands")
    if status == "success":
        return str(data.get("message") or "Command completed")
    if status == "ignored":
        return str(data.get("reason") or "Command was ignored")
    if status == "error":
        return str(
            data.get("message")
            or data.get("error")
            or data.get("reason")
            or "Unknown error"
        )
    return str(data.get("message") or status or "Response received")


def _format_structured_data(data: object) -> None:
    console.print()
    console.print(f"[{DIM}]agent output[/]")

    if isinstance(data, str):
        output = Table.grid(padding=(0, 1))
        output.style = BG
        output.add_column(width=2)
        output.add_column()
        output.add_row("", Text(data, style=f"green {BG}"))
        console.print(output)
        return

    console.print(
        Syntax(
            json.dumps(data, indent=2),
            "json",
            theme="monokai",
            line_numbers=False,
            word_wrap=True,
            background_color="default",
        )
    )


def _format_response(
    response_text: str,
    status_code: int | None = None,
    elapsed_seconds: float | None = None,
) -> None:
    try:
        parsed = json.loads(response_text)
        data = _normalize_payload(parsed)

        if not isinstance(data, Mapping):
            style = "red" if status_code and status_code >= 400 else "cyan"
            title = f"HTTP {status_code}" if status_code else "Response"
            _print_status(title, Text(str(data), style=f"bold {style} {BG}"), style)
            return

        if "logs" in data:
            _format_logs(data["logs"])

        status_name = str(data.get("status") or "response")
        border_style, title = STATUS_THEME.get(status_name, ("cyan", "Response"))
        if status_code and status_code >= 400 and status_name != "error":
            border_style, title = "red", f"HTTP {status_code}"

        has_agent_data = status_name == "success" and data.get("data") is not None
        message = _message_for_status(data, status_name)
        if has_agent_data and message == "Command completed":
            message = "agent-browser returned output"

        body = Text(message, style=f"bold {border_style} {BG}")
        hint = data.get("hint")
        if hint:
            body.append("\n")
            body.append(str(hint), style=DIM)
        _print_status(title, body, border_style, elapsed_seconds)

        details = _details_table(data)
        if details:
            console.print()
            console.print(f"[{DIM}]details[/]")
            console.print(details)

        if has_agent_data:
            _format_structured_data(data["data"])
    except json.JSONDecodeError:
        console.print(response_text.strip())


async def _needs_login() -> bool:
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                DAEMON_AGENT_BROWSER_COMMAND_URL,
                json={"command": "needs_login"},
            )
        data = json.loads(response.text)
        if isinstance(data, Mapping):
            return bool(data.get("needs_login"))
    except Exception:
        pass
    return False


def _print_signin_notice() -> None:
    body = Text(
        "A Chrome window will open at https://myaccount.google.com/.\n"
        "Sign in to your Google account, then close the window when you're done.\n"
        "Wolfie is waiting.",
        style=f"bold yellow {BG}",
    )
    _print_status("Sign in required", body, "yellow")


async def _post_command(command: str) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        try:
            started_at = time.perf_counter()
            with console.status(
                f"[cyan on grey11]Running[/] [bold white on grey11]{escape(command)}[/]",
                spinner="dots",
            ):
                response = await client.post(
                    DAEMON_AGENT_BROWSER_COMMAND_URL,
                    json={"command": command},
                )
            elapsed = time.perf_counter() - started_at
            _format_response(response.text, response.status_code, elapsed)
        except httpx.RequestError as e:
            body = Text(f"Could not reach the daemon: {e}", style=f"bold red {BG}")
            body.append("\nRun wolfie again to restart the local daemon.", style=DIM)
            _print_status("Connection Error", body, "red")
        except Exception as e:
            _print_status("Error", Text(str(e), style=f"bold red {BG}"), "red")


def _format_plan_event(data: Mapping[str, object]) -> None:
    plan = data.get("plan") if isinstance(data.get("plan"), list) else []
    next_task = str(data.get("next_task") or "")
    reason = str(data.get("reason") or "")

    body = Text()
    if reason:
        body.append(reason, style=f"white {BG}")
    for idx, item in enumerate(plan, start=1):
        body.append(f"\n{idx}. {item}", style=DIM)
    if next_task:
        body.append("\nnext: ", style=DIM)
        body.append(next_task, style=f"bold cyan {BG}")

    _print_status("plan", body, "cyan")


def _format_agent_event(data: Mapping[str, object]) -> None:
    event_type = str(data.get("type") or "event")

    if event_type == "status":
        console.print(f"[{DIM}]{data.get('message', '')}[/]")
        return
    if event_type == "plan":
        _format_plan_event(data)
        return
    if event_type == "action":
        body = Text(str(data.get("command") or ""), style=f"bold cyan {BG}")
        validation_command = data.get("validation_command")
        if validation_command:
            body.append("\nvalidate: ", style=DIM)
            body.append(str(validation_command), style=f"cyan {BG}")
        thought = data.get("thought")
        if thought:
            body.append("\n")
            body.append(str(thought), style=DIM)
        _print_status("agent-browser", body, "cyan")
        return
    if event_type == "observation":
        ok = bool(data.get("ok"))
        style = "green" if ok else "yellow"
        output = str(data.get("output") or "")
        if not output:
            output = "No output"
        if data.get("skipped"):
            output = f"Skipped duplicate side-effect action.\n{output}"
        if data.get("side_effect"):
            output = f"{output}\nside effect: yes"
        criteria = data.get("success_criteria")
        if criteria:
            output = f"{output}\ncriteria: {criteria}"
        validation_command = data.get("validation_command")
        validation_output = str(data.get("validation_output") or "")
        if validation_command:
            validation_status = "ok" if data.get("validation_ok") else "failed"
            output = (
                f"{output}\nvalidation ({validation_status}): "
                f"{validation_command}\n{validation_output or 'No validation output'}"
            )
        _print_status("observation", Text(output, style=f"{style} {BG}"), style)
        return
    if event_type == "executor":
        status = str(data.get("status") or "done")
        style = "green" if status == "done" else "yellow"
        message = str(data.get("reason") or status)
        thought = data.get("thought")
        if thought:
            message = f"{message}\n{thought}"
        _print_status("executor", Text(message, style=f"{style} {BG}"), style)
        return
    if event_type == "need_user":
        question = str(data.get("question") or "Agent needs input.")
        choices = data.get("choices") if isinstance(data.get("choices"), list) else []
        body = Text(question, style=f"bold yellow {BG}")
        for idx, choice in enumerate(choices, start=1):
            body.append(f"\n{idx}. {choice}", style=DIM)
        body.append("\nreply: ", style=DIM)
        body.append("input <answer>", style=f"bold cyan {BG}")
        _print_status("need input", body, "yellow")
        return
    if event_type == "final":
        _print_status("final", Text(str(data.get("text") or ""), style=f"bold green {BG}"), "green")
        return
    if event_type == "done":
        console.print(f"[{DIM}]agent run complete[/]")
        return
    if event_type == "error":
        message = str(data.get("message") or "")
        if data.get("detail"):
            message = f"{message}\n{data['detail']}"
        _print_status("error", Text(message, style=f"bold red {BG}"), "red")
        return

    _print_status("event", Text(str(dict(data)), style=f"white {BG}"), "cyan")


def _agent_headers() -> dict[str, str]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    model = os.getenv("WOLFIE_GEMINI_MODEL")
    thinking_level = os.getenv("WOLFIE_GEMINI_THINKING_LEVEL")
    headers = {}
    if api_key:
        headers["X-Wolfie-Gemini-Api-Key"] = api_key
    if model:
        headers["X-Wolfie-Gemini-Model"] = model
    if thinking_level:
        headers["X-Wolfie-Gemini-Thinking-Level"] = thinking_level
    return headers


async def _stream_agent_request(url: str, payload: dict[str, object], label: str) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        try:
            with console.status(
                f"[cyan on grey11]{escape(label)}[/]",
                spinner="dots",
            ):
                async with client.stream(
                    "POST",
                    url,
                    headers=_agent_headers(),
                    json=payload,
                ) as response:
                    if response.status_code >= 400:
                        text = await response.aread()
                        _format_response(text.decode(), response.status_code)
                        return
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            _format_agent_event(json.loads(line))
                        except json.JSONDecodeError:
                            console.print(line)
        except httpx.RequestError as e:
            body = Text(f"Could not reach the daemon: {e}", style=f"bold red {BG}")
            body.append("\nRun wolfie again to restart the local daemon.", style=DIM)
            _print_status("Connection Error", body, "red")
        except Exception as e:
            _print_status("Error", Text(str(e), style=f"bold red {BG}"), "red")


async def _post_agent_prompt(prompt: str) -> None:
    await _stream_agent_request(
        DAEMON_AGENT_PROMPT_URL,
        {"prompt": prompt, "thread_id": "default"},
        f"Planning {prompt}",
    )


async def _post_agent_input(message: str) -> None:
    await _stream_agent_request(
        DAEMON_AGENT_INPUT_URL,
        {"message": message, "thread_id": "default"},
        f"Sending input {message}",
    )


def _format_agent_state(data: Mapping[str, object]) -> None:
    if data.get("status") == "missing":
        _print_status(
            "state",
            Text(str(data.get("message") or "No agent session."), style=f"yellow {BG}"),
            "yellow",
        )
        return

    body = Text()
    body.append(str(data.get("task_status") or "unknown"), style=f"bold cyan {BG}")
    goal = data.get("goal")
    if goal:
        body.append("\ngoal: ", style=DIM)
        body.append(str(goal), style=f"white {BG}")
    body.append(
        f"\nsteps: {data.get('step_count', 0)} / {data.get('max_steps', 0)}",
        style=DIM,
    )
    next_task = data.get("next_task")
    if next_task:
        body.append("\nnext: ", style=DIM)
        body.append(str(next_task), style=f"white {BG}")
    pending_question = data.get("pending_question")
    if pending_question:
        body.append("\nquestion: ", style=DIM)
        body.append(str(pending_question), style=f"bold yellow {BG}")

    _print_status("agent state", body, "cyan")

    plan = data.get("plan") if isinstance(data.get("plan"), list) else []
    if plan:
        table = Table.grid(padding=(0, 1))
        table.style = BG
        table.add_column(style=DIM, no_wrap=True)
        table.add_column(style=f"white {BG}")
        for idx, item in enumerate(plan, start=1):
            table.add_row(str(idx), str(item))
        console.print()
        console.print(f"[{DIM}]plan[/]")
        console.print(table)

    latest = data.get("last_observation")
    if isinstance(latest, Mapping):
        output = str(latest.get("output") or latest.get("error") or "")
        if output:
            _print_status(
                "last observation",
                Text(output[:2000], style=f"green {BG}"),
                "green",
            )


async def _get_agent_state() -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.get(DAEMON_AGENT_STATE_URL)
            _format_agent_state(json.loads(response.text))
        except httpx.RequestError as e:
            body = Text(f"Could not reach the daemon: {e}", style=f"bold red {BG}")
            body.append("\nRun wolfie again to restart the local daemon.", style=DIM)
            _print_status("Connection Error", body, "red")
        except Exception as e:
            _print_status("Error", Text(str(e), style=f"bold red {BG}"), "red")


async def _run(command: str) -> None:
    if command.lower() == "start" and await _needs_login():
        _print_signin_notice()
    if command == "prompt":
        _print_status(
            "error",
            Text("Usage: prompt <task>", style=f"bold red {BG}"),
            "red",
        )
        return
    if command.startswith("prompt "):
        await _post_agent_prompt(command[len("prompt ") :].strip())
        return
    if command == "input":
        _print_status(
            "error",
            Text("Usage: input <answer>", style=f"bold red {BG}"),
            "red",
        )
        return
    if command.startswith("input "):
        await _post_agent_input(command[len("input ") :].strip())
        return
    if command.startswith("reply "):
        await _post_agent_input(command[len("reply ") :].strip())
        return
    if command == "state":
        await _get_agent_state()
        return
    await _post_command(command)


def send_command(text: str) -> None:
    command = text.strip()
    if not command:
        return

    asyncio.run(_run(command))
