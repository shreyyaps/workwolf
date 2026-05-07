import typer
from rich.console import Console

app = typer.Typer()
console = Console(style="on grey11")

DAEMON_HEALTH = "http://127.0.0.1:8765/health"
DAEMON_AGENT_BROWSER_COMMAND_URL = (
    "http://127.0.0.1:8765/run-agent-browser-vercel-command"
)
