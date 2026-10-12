"""Screenshots of the interface in a browser, plus a few end-to-end checks (temporary)."""
# ruff: noqa: S101, S110

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import Browser, Page, expect, sync_playwright

VIEWPORT = {"width": 1200, "height": 780}


def start_host() -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "vethuq_desktop", "--no-window"],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    line = process.stdout.readline()
    if not line:
        raise SystemExit("vethuq-desktop --no-window printed no URL")
    return process, json.loads(line)["url"]


def open_page(browser: Browser, url: str) -> Page:
    page = browser.new_context(viewport=VIEWPORT, color_scheme="light").new_page()
    page.goto(url)
    expect(page.get_by_test_id("app-shell")).to_be_visible()
    return page


def shot(page: Page, out: Path, name: str) -> None:
    page.wait_for_timeout(400)  # let animations settle
    page.screenshot(path=str(out / f"browser-{name}.png"))
    print("captured", name)


def run(browser: Browser, out: Path) -> None:
    process, url = start_host()
    try:
        page = open_page(browser, url)
        assert page.url.rstrip("/").endswith(
            url.split("/?")[0]
        ), "token should be gone from the URL"
        assert "?t=" not in page.url

        # The start-up link works once.
        second = browser.new_context().new_page()
        assert second.goto(url).status == 403
        # And the API refuses a visitor without a session.
        assert second.request.get(url.split("/?")[0] + "/api/about").status == 401

        expect(page.get_by_text("Ready")).to_be_visible()
        expect(page.get_by_text("VethuQ 0.")).to_be_visible()
        for scheme in ("light", "dark"):
            page.emulate_media(color_scheme=scheme)
            page.get_by_role("tab", name="Home").click()
            expect(page.get_by_text("Welcome to VethuQ")).to_be_visible()
            shot(page, out, f"home-{scheme}")
            page.get_by_role("tab", name="About").click()
            expect(page.get_by_text("Database schema")).to_be_visible()
            shot(page, out, f"about-{scheme}")
            page.get_by_role("tab", name="Settings").click()
            expect(page.get_by_text("Use my system setting")).to_be_visible()
            shot(page, out, f"settings-{scheme}")

        # Title-bar buttons talk to the host (simulated here).
        page.get_by_role("tab", name="Home").click()
        page.get_by_role("button", name="Maximize").click()
        expect(page.get_by_role("button", name="Restore")).to_be_visible()
        page.get_by_role("button", name="Restore").click()
        expect(page.get_by_role("button", name="Maximize")).to_be_visible()

        # Choosing a theme overrides the system setting and survives a reload.
        page.get_by_role("tab", name="Settings").click()
        page.get_by_role("radio", name="Dark").check()
        page.emulate_media(color_scheme="light")
        page.reload()
        expect(page.get_by_test_id("app-shell")).to_be_visible()
        assert page.evaluate("document.documentElement.style.colorScheme") == "dark"
        shot(page, out, "settings-dark-chosen")
        print("browser checks passed")
    finally:
        process.terminate()
        process.wait(timeout=10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("shots"))
    parser.add_argument("--channel", help="browser channel to use, e.g. msedge")
    parser.add_argument("--executable", help="path to a Chromium binary")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel, executable_path=args.executable)
        try:
            run(browser, args.out)
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
