from playwright.sync_api import sync_playwright
import os

profile_dir = os.path.expanduser("~/cli-agent-profile")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        headless=False,
        args=["--remote-debugging-port=9220"],
    )

    page = context.new_page()
    page.goto("https://example.com")

    input("Press Enter to close...")