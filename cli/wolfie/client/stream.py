import asyncio

import httpx
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from ..core.config import DAEMON_STREAM_URL, console


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


def handle_command(text: str) -> None:
    parts = text.split()
    asyncio.run(stream_command(parts))

