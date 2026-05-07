from ..core.config import console


def show_node_detected(version: str) -> None:
    console.print(f"[green]Node already installed on system ({version}).[/green]")


def show_node_download(version: str) -> None:
    console.print(f"[yellow]Downloading Node {version}...[/yellow]")


def show_node_extract() -> None:
    console.print("[yellow]Extracting Node...[/yellow]")


def show_node_installed() -> None:
    console.print("[green]Node installed successfully.[/green]")


def show_agent_browser_installing() -> None:
    console.print("[yellow]agent-browser is installing...[/yellow]")


def show_agent_browser_checking() -> None:
    console.print("[dim]Checking agent-browser...[/dim]")


def show_agent_browser_detected(path: str, version: str | None = None) -> None:
    suffix = f" ({version})" if version else f" at {path}"
    console.print(f"[green]agent-browser already installed{suffix}.[/green]")


def show_agent_browser_installed() -> None:
    console.print("[green]agent-browser installed successfully.[/green]")
