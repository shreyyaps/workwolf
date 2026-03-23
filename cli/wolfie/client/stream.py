import asyncio

import httpx

from ..core.config import (
    DAEMON_AGENT_BROWSER_COMMAND_URL,
    console,
)


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

    asyncio.run(
        post_command(
            DAEMON_AGENT_BROWSER_COMMAND_URL,
            {"command": " ".join(parts)},
        )
    )
