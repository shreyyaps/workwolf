from ..core.config import console


def show_node_detected(version: str) -> None:
    console.print(f"[green]Node already installed on system ({version}).[/green]")


def show_node_download(version: str) -> None:
    console.print(f"[yellow]Downloading Node {version}...[/yellow]")


def show_node_extract() -> None:
    console.print("[yellow]Extracting Node...[/yellow]")


def show_node_installed() -> None:
    console.print("[green]Node installed successfully.[/green]")


def show_node_reinstall(current: str, target: str) -> None:
    console.print(
        f"[yellow]Node version mismatch ({current}). Reinstalling {target}...[/yellow]"
    )


def show_agent_browser_installing() -> None:
    console.print("[yellow]agent-browser is installing...[/yellow]")


def show_agent_browser_installed() -> None:
    console.print("[green]agent-browser installed successfully.[/green]")
