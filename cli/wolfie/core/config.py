import typer
from prompt_toolkit.completion import WordCompleter
from rich.console import Console

app = typer.Typer()
console = Console()

DAEMON_HEALTH = "http://127.0.0.1:8765/health"
DAEMON_STREAM_URL = "http://127.0.0.1:8765/run-stream"
DAEMON_AGENT_BROWSER_COMMAND_URL = (
    "http://127.0.0.1:8765/run-agent-browser-vercel-command"
)

COMMANDS = ["apply", "status", "login", "exit", "quit", "test", "start", "open"]
completer = WordCompleter(COMMANDS, ignore_case=True)
