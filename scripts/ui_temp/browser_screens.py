"""Screenshots of the interface in a browser, plus a few end-to-end checks (temporary)."""
# ruff: noqa: S101, S110

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Browser, Page, expect, sync_playwright

VIEWPORT = {"width": 1200, "height": 780}


def start_host() -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "vethuq_desktop", "--no-window"],
        stdout=subprocess.PIPE,
        text=True,
        # A throw-away data folder, so the settings the checks change are not the user's own.
        env={**os.environ, "VETHUQ_HOME": tempfile.mkdtemp(prefix="vethuq-ui-")},
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
            expect(page.get_by_text("Document intelligence and evidence")).to_be_visible()
            shot(page, out, f"home-{scheme}")
            page.get_by_role("tab", name="About").click()
            expect(page.get_by_text("Database schema")).to_be_visible()
            expect(page.get_by_role("tab", name="Add-ons (")).to_be_visible()
            shot(page, out, f"about-{scheme}")
            page.get_by_role("tab", name="File types (").click()
            expect(page.get_by_role("table", name="File types")).to_be_visible()
            shot(page, out, f"about-file-types-{scheme}")
            page.get_by_role("tab", name="Settings").click()
            page.get_by_role("tab", name="General").click()
            expect(page.get_by_text("Use my system setting")).to_be_visible()
            shot(page, out, f"settings-{scheme}")

        # Indexing settings: change, persist across a reload, show errors, reset.
        page.get_by_role("tab", name="Settings").click()
        page.get_by_role("tab", name="Indexing").click()
        expect(page.get_by_text("Files indexed at once")).to_be_visible()
        shot(page, out, "settings-indexing")
        gpu = page.get_by_role("switch", name="Use the graphics card for OCR")
        gpu.click()
        expect(gpu).to_be_checked()
        page.get_by_role("combobox", name="Files indexed at once").click()
        page.get_by_role("option", name="4", exact=True).click()
        expect(page.get_by_role("combobox", name="Files indexed at once")).to_have_text("4")
        page.get_by_role("switch", name="Show advanced settings").click()
        expect(page.get_by_text("Wait for files to stop changing")).to_be_visible()
        shot(page, out, "settings-indexing-changed")
        page.reload()
        page.get_by_role("tab", name="Indexing").click()
        expect(page.get_by_role("switch", name="Use the graphics card for OCR")).to_be_checked()
        expect(page.get_by_role("combobox", name="Files indexed at once")).to_have_text("4")
        page.get_by_role("button", name="Reset to default: Files indexed at once").click()
        expect(page.get_by_role("combobox", name="Files indexed at once")).to_have_text(
            "Automatic (sized to this computer)"
        )

        # Typed numbers save when committed (Enter or leaving the field).
        retries = page.get_by_role("spinbutton", name="Retries for a failed file")
        retries.fill("7")
        retries.press("Tab")
        expect(page.get_by_test_id("setting-index.retry_attempts")).to_contain_text("Applies")
        page.reload()
        page.get_by_role("tab", name="Indexing").click()
        expect(page.get_by_role("spinbutton", name="Retries for a failed file")).to_have_value("7")
        page.get_by_role("button", name="Reset to default: Retries for a failed file").click()
        expect(page.get_by_role("spinbutton", name="Retries for a failed file")).to_have_value("3")

        # General: languages and metrics.
        page.get_by_role("tab", name="General").click()
        expect(page.get_by_test_id("setting-languages.languages")).to_be_visible()
        metrics = page.get_by_role("switch", name="Share anonymous usage metrics")
        metrics.click()
        expect(metrics).to_be_checked()
        page.get_by_role("combobox", name="Languages to read documents in").click()
        expect(page.get_by_role("menuitemcheckbox", name="English")).to_be_visible()
        shot(page, out, "settings-general-languages")
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Reset to default: Share anonymous usage metrics").click()
        expect(metrics).not_to_be_checked()
        shot(page, out, "settings-general")

        # General: the update check, and the read-only skipped/snoozed update notices.
        updates = page.get_by_role("combobox", name="Check for updates")
        updates.click()
        page.get_by_role("option", name="Notify only: check and tell me").click()
        expect(updates).to_have_text("Notify only: check and tell me")
        page.get_by_role("switch", name="Show advanced settings").click()
        expect(page.get_by_test_id("setting-updates.skipped_version")).to_contain_text("None")
        expect(page.get_by_role("button", name="Clear: Skipped update")).to_be_disabled()
        shot(page, out, "settings-general-updates")
        page.get_by_role("button", name="Reset to default: Check for updates").click()
        expect(updates).to_have_text("On: check and offer to update")

        # Sources: retention in minutes, with a readable duration.
        page.get_by_role("tab", name="Sources").click()
        expect(page.get_by_text("7 days", exact=True)).to_be_visible()
        retention = page.get_by_role("spinbutton", name="Keep a removed source for")
        retention.fill("120")
        retention.press("Enter")
        expect(page.get_by_text("2 hours", exact=True)).to_be_visible()
        shot(page, out, "settings-sources")
        page.get_by_role("button", name="Reset to default: Keep a removed source for").click()
        expect(page.get_by_text("7 days", exact=True)).to_be_visible()

        # Processing: tiers and the hybrid options.
        page.get_by_role("tab", name="Processing").click()
        expect(page.get_by_test_id("setting-tiers.default")).to_be_visible()
        page.get_by_role("combobox", name="OCR phases sent to GitHub").click()
        page.get_by_role("menuitemcheckbox", name="Deep").click()
        page.keyboard.press("Escape")
        expect(page.get_by_role("combobox", name="OCR phases sent to GitHub")).to_contain_text(
            "Deep"
        )
        page.get_by_role("switch", name="Show advanced settings").click()
        expect(page.get_by_text("Most pages in one remote job")).to_be_visible()
        shot(page, out, "settings-processing")
        page.get_by_role("button", name="Reset to default: OCR phases sent to GitHub").click()

        # Results: confidence bands, saved together and refused when they do not rise.
        page.get_by_role("tab", name="Results").click()
        expect(page.get_by_role("spinbutton", name="Low from")).to_have_value("70")
        page.get_by_role("spinbutton", name="Medium from").fill("95")
        page.get_by_role("spinbutton", name="Medium from").press("Tab")
        expect(page.get_by_text("Each band must start higher")).to_be_visible()
        expect(page.get_by_role("button", name="Apply")).to_be_disabled()
        page.get_by_role("spinbutton", name="Medium from").fill("75")
        page.get_by_role("spinbutton", name="Medium from").press("Tab")
        page.get_by_role("spinbutton", name="Low from").fill("60")
        page.get_by_role("spinbutton", name="Low from").press("Tab")
        page.get_by_role("button", name="Apply").click()
        expect(
            page.get_by_role("button", name="Reset to default: Confidence bands")
        ).to_be_enabled()
        shot(page, out, "settings-results")
        page.reload()
        page.get_by_role("tab", name="Results").click()
        expect(page.get_by_role("spinbutton", name="Low from")).to_have_value("60")
        page.get_by_role("button", name="Reset to default: Confidence bands").click()
        expect(page.get_by_role("spinbutton", name="Low from")).to_have_value("70")

        # System: logs and database.
        page.get_by_role("tab", name="System").click()
        level = page.get_by_role("combobox", name="Log detail")
        level.click()
        page.get_by_role("option", name="Debug: everything, for troubleshooting").click()
        expect(level).to_have_text("Debug: everything, for troubleshooting")
        days = page.get_by_role("spinbutton", name="Keep log files for")
        days.fill("30")
        days.press("Tab")
        expect(page.get_by_test_id("setting-logs.retention_days")).to_contain_text("Takes effect")
        page.get_by_role("switch", name="Show advanced settings").click()
        expect(page.get_by_text("1 day", exact=True)).to_be_visible()
        shot(page, out, "settings-system")
        page.reload()
        page.get_by_role("tab", name="System").click()
        expect(page.get_by_role("combobox", name="Log detail")).to_have_text(
            "Debug: everything, for troubleshooting"
        )
        expect(page.get_by_role("spinbutton", name="Keep log files for")).to_have_value("30")
        page.get_by_role("button", name="Reset to default: Log detail").click()
        page.get_by_role("button", name="Reset to default: Keep log files for").click()
        expect(page.get_by_role("combobox", name="Log detail")).to_have_text(
            "Info: normal activity"
        )
        expect(page.get_by_role("spinbutton", name="Keep log files for")).to_have_value("15")

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
