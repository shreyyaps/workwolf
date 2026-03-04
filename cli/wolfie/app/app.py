import typer

from ..core.config import app
from ..runtime.daemon import ensure_daemon
from ..runtime.node import ensure_runtime_dependencies
from ..ui.shell import interactive_shell


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Wolfie interactive CLI."""
    if ctx.invoked_subcommand is None:
        ensure_runtime_dependencies()
        ensure_daemon()
        interactive_shell()


if __name__ == "__main__":
    app()
