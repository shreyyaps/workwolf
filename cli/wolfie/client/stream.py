import asyncio

import httpx
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from ..core.config import (
    DAEMON_AGENT_BROWSER_COMMAND_URL,
    DAEMON_STREAM_URL,
    console,
)


async def stream_command(parts: list[str]) -> None:
    output_text = Text()

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            DAEMON_STREAM_URL,
            json={"args": parts},
        ) as response:
            spinner = Spinner("dots", text=" Working...")
            with Live(spinner, console=console, refresh_per_second=12) as live:
                async for chunk in response.aiter_text():
                    spinner.text = " Receiving..."
                    output_text.append(chunk)
                    live.update(output_text)

    console.print()


async def post_command(url: str, payload: dict) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        response = await client.post(url, json=payload)
        if response.headers.get("content-type", "").startswith("application/json"):
            console.print(response.text)
        else:
            console.print(response.text.strip())


def handle_command(text: str) -> None:
    parts = text.split()
    if not parts:
        return

    if parts[0] == "start":
        asyncio.run(stream_command(parts))
        return

    if parts[0] == "open":
        asyncio.run(
            post_command(
                DAEMON_AGENT_BROWSER_COMMAND_URL,
                {"command": " ".join(parts)},
            )
        )
        return

    asyncio.run(stream_command(parts))
