from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import asyncio
from playwright.async_api import async_playwright
app = FastAPI()


async def fake_stream(args):
    for word in ["Wolfie ", "is ", "processing ", "your ", "request...\n"]:
        yield word
        await asyncio.sleep(0.3)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run-stream")
async def run_stream(payload: dict):
    args = payload.get("args", [])
   
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="./user-data",
            channel="chrome",
            headless=False,
        )

        page = await context.new_page()
        await page.goto("https://www.google.com")
    return StreamingResponse(fake_stream(args), media_type="text/plain")