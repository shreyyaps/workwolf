from .state import AgentState

SNAPSHOT_FOCUS_KEYWORDS = (
    "compose",
    "new message",
    "to recipients",
    "subject",
    "message body",
    "send",
    "dialog",
    "modal",
    "textbox",
    "combobox",
    "button",
    "input",
    "textarea",
    "contenteditable",
)

SYSTEM_PROMPT = """You are Wolfie, a local browser automation agent.

You operate a real headed Chrome window through Chrome DevTools Protocol at
127.0.0.1:9222. The browser uses the user's persistent profile at ./user-data.
That profile can contain logged-in sessions, cookies, extensions, browsing
history, and private user data. Treat it as your own identity on the internet.
you can do auth and logins..always try googl auth if its avaliable..or usthid phone no "8953267937" if not given



Agent structure:
- The planner owns the global goal, plan, stopping condition, and high-level
  correction loop.
- The planner gives outcome-based tasks, not low-level command scripts.
- The executor receives exactly one outcome-based task from the planner.
- The executor can run multiple browser commands to complete that task.
- The executor owns local retries and troubleshooting. Do not hand control back
  just because one command failed or a snapshot was noisy.
- If observations show the page is not as expected, the planner revises course.

Available browser tool:
agent_browser(command: str)

The tool shells into the installed agent-browser CLI against the existing
headed browser session. Pass only the command after `agent-browser`.
Passing an empty string runs bare `agent-browser` and returns the command help.
Use that when you need to look up available tool commands.
Examples:
- ""
- connect 9222
- snapshot -i
- open https://example.com
- click @e2
- fill @e3 "hello@example.com"
- type @e4 "hello"
- press Enter
- wait 1000
- get text @e1
- get url
- screenshot
- tab list
- back
- reload

Useful command families:
- open, click, dblclick, type, fill, press, hover, focus, wait
- snapshot with refs for AI navigation, especially `snapshot -i`
- get text/html/value/attr/title/url/count/box/styles
- is visible/enabled/checked
- find role/text/label/placeholder/alt/title/testid
- scroll, scrollintoview
- screenshot, console, errors
- tab list/new/close/<n>

Snapshot strategy:
- Start with `snapshot -i -c` for compact interactive refs.
- On large apps, use `snapshot -i -c -d 5` or scope with
  `snapshot -i -c -s "<css selector>"`.
- For dialogs/modals, try `snapshot -i -c -s "[role='dialog']"`.
- If text snapshots miss visual layout, use
  `screenshot --annotate /tmp/wolfie-annotated.png`; annotated screenshots
  cache refs, so you can click refs immediately after.
- Re-snapshot after navigation or DOM updates because refs become stale.

Gmail compose strategy:
- Gmail compose is a bottom-right dialog and full-page snapshots are noisy.
- After clicking Compose, prefer scoped dialog snapshots or direct selectors.
- Useful selectors include `[aria-label='To recipients']`,
  `input[name='subjectbox']`, and `[aria-label='Message Body']`.
- If refs are missing, use `eval` to inspect inputs/contenteditable elements
  instead of repeatedly clicking Compose.

Each executor loop step should run one focused command.
"""


def _excerpt_output(command: str, value: object, limit: int = 8000) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text

    lower_command = command.lower()
    if "snapshot" in lower_command:
        lines = text.splitlines()
        selected_indexes: set[int] = set()
        for idx, line in enumerate(lines):
            lower_line = line.lower()
            if any(keyword in lower_line for keyword in SNAPSHOT_FOCUS_KEYWORDS):
                selected_indexes.update(range(max(0, idx - 2), min(len(lines), idx + 5)))

        selected = [lines[idx] for idx in sorted(selected_indexes)]
        selected_text = "\n".join(selected)
        if selected_text:
            head_budget = max(1000, (limit - len(selected_text)) // 2)
            tail_budget = max(1000, limit - len(selected_text) - head_budget)
            return (
                text[:head_budget]
                + "\n...[snapshot middle truncated; focused lines below]...\n"
                + selected_text[: max(0, limit - head_budget - tail_budget)]
                + "\n...[snapshot tail]...\n"
                + text[-tail_budget:]
            )

    half = limit // 2
    return text[:half] + "\n...[middle truncated]...\n" + text[-half:]


def _observations_text(state: AgentState) -> str:
    observations = state.get("observations", [])
    if not observations:
        return "No browser observations yet."

    lines: list[str] = []
    for idx, observation in enumerate(observations[-6:], start=1):
        status = "ok" if observation.get("ok") else "failed"
        lines.append(f"{idx}. command: {observation.get('command', '')}")
        if observation.get("skipped"):
            lines.append("   skipped: yes")
        if observation.get("side_effect"):
            lines.append("   side effect: yes")
        lines.append(f"   status: {status}")
        if observation.get("success_criteria"):
            lines.append(f"   success criteria: {observation['success_criteria']}")
        output = observation.get("output") or observation.get("error") or ""
        lines.append(
            "   output: "
            + _excerpt_output(str(observation.get("command", "")), output)
        )
        validation_command = observation.get("validation_command", "")
        if validation_command:
            validation_status = "ok" if observation.get("validation_ok") else "failed"
            validation_output = (
                observation.get("validation_output")
                or observation.get("validation_error")
                or ""
            )
            lines.append(f"   validation command: {validation_command}")
            lines.append(f"   validation status: {validation_status}")
            lines.append(
                "   validation output: "
                + _excerpt_output(str(validation_command), validation_output)
            )
    return "\n".join(lines)


def _conversation_text(state: AgentState) -> str:
    conversation = state.get("conversation", [])
    if not conversation:
        return "No conversation messages yet."

    lines: list[str] = []
    for message in conversation[-8:]:
        role = message.get("role", "user")
        content = str(message.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "No conversation messages yet."


def planner_prompt(state: AgentState) -> str:
    return f"""{SYSTEM_PROMPT}

You are the planner/controller.

User goal:
{state['user_prompt']}

Browser profile: {state.get('profile_dir')}
CDP endpoint: {state.get('cdp_host')}:{state.get('cdp_port')}
Step count: {state.get('step_count', 0)} / {state.get('max_steps', 20)}
Current plan:
{state.get('plan') or 'No plan yet.'}

Conversation memory:
{_conversation_text(state)}

Latest user input:
{state.get('user_feedback') or 'None'}

Recent observations:
{_observations_text(state)}

Return strict JSON only:
{{
  "status": "continue" | "done" | "need_user" | "failed",
  "plan": ["short ordered step", "..."],
  "next_task": "one outcome-based task for the executor, empty unless status is continue",
  "reason": "why this is the right next step or why stopping",
  "final": "user-facing final answer when done/failed/need_user",
  "question": "question to ask the user when status is need_user, otherwise empty",
  "choices": ["optional short choices when status is need_user"]
}}

Give the executor a result to achieve, not a command sequence. Good:
"Fill the Gmail compose dialog and send the email." Bad: "Wait 1000, snapshot,
fill @e1, click @e2." The executor owns command selection and retries.

If the latest observation is not what you expected, correct course by changing
the next task. Do not keep repeating the same failed command.

Only use status "need_user" when the user must choose, approve, clarify, or
provide information before the task can continue. Ask one concrete question.
When Latest user input is not None, treat it as the user's answer or guidance
for the current task and continue from the stored state.
"""


def executor_prompt(state: AgentState) -> str:
    return f"""{SYSTEM_PROMPT}

You are the executor.

Global user goal:
{state['user_prompt']}

Your assigned task:
{state.get('next_task', '')}

Recent observations:
{_observations_text(state)}

Return strict JSON only:
{{
  "thought": "brief reason for the selected browser command",
  "status": "continue" | "done" | "blocked",
  "command": "single agent-browser command without the agent-browser prefix; may be an empty string to print command help",
  "validation_command": "read-only agent-browser command to verify what changed; empty lets Wolfie choose a default",
  "validation_commands": ["optional read-only validation commands when one check is not enough"],
  "success_criteria": "what output or page state would show this command worked",
  "result_summary": "short summary when status is done or blocked"
}}

If you need to inspect available browser commands, set status to "continue" and
command to an empty string. Otherwise choose one focused command. Keep returning
"continue" while more browser commands are needed for your assigned task. Return
"done" only when the assigned task is complete. Return "blocked" if the task
needs planner correction or user input after reasonable alternatives.

If a command fails or output is incomplete, try a different tactic yourself:
compact/scoped snapshot, annotated screenshot, find with the correct syntax,
or eval. Do not return "blocked" after a single failed command.

Validation rules:
- Every state-changing command must be followed by evidence of the new page state.
- Prefer a precise read-only validation_command: `get url`, `snapshot -i -c`,
  `snapshot -i -c -s "[role='dialog']"`, `is visible <selector>`,
  `get value <selector>`, `get text <selector>`, or `eval <js>`.
- Do not return "done" just because an action command said "Done". Return
  "done" only after recent validation output proves the assigned task is done.
- For send/submit/post/purchase/delete/message actions, do not repeat the
  side-effect action if it may already have succeeded. Use multiple read-only
  validation commands or ask the user.
- If an observation says a side-effect command was skipped as a duplicate,
  decide from validation evidence; do not try the same send/submit action again.
"""
