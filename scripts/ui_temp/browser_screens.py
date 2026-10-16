"""Screenshots of the interface in a browser, plus a few end-to-end checks (temporary)."""
# ruff: noqa: S101, S110

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Browser, Page, expect, sync_playwright

VIEWPORT = {"width": 1200, "height": 780}


def start_host(env: dict[str, str] | None = None) -> tuple[subprocess.Popen[str], str]:
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "vethuq_desktop", "--no-window"],
        stdout=subprocess.PIPE,
        text=True,
        # A throw-away data folder, so the settings the checks change are not the user's own.
        env=env or {**os.environ, "VETHUQ_HOME": tempfile.mkdtemp(prefix="vethuq-ui-")},
    )
    assert process.stdout is not None
    line = process.stdout.readline()
    if not line:
        raise SystemExit("vethuq-desktop --no-window printed no URL")
    return process, json.loads(line)["url"]


def open_page(browser: Browser, url: str) -> Page:
    context = browser.new_context(viewport=VIEWPORT, color_scheme="light")
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=url.split("/?")[0])
    page = context.new_page()
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
        assert page.url.rstrip("/").endswith(url.split("/?")[0]), (
            "token should be gone from the URL"
        )
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

        # Search: grouped, with the normalizers and each engine's own options.
        page.get_by_role("tab", name="Settings").click()
        page.get_by_role("tab", name="Search").click()
        expect(page.get_by_role("heading", name="Searching")).to_be_visible()
        expect(page.get_by_role("heading", name="How text is matched")).to_be_visible()
        expect(page.get_by_role("heading", name="Similar (fuzzy) engine")).to_be_visible()
        shot(page, out, "settings-search")
        engine = page.get_by_role("combobox", name="Default search engine")
        engine.click()
        page.get_by_role("option", name="Contains (like)").click()
        expect(engine).to_have_text("Contains (like)")
        case = page.get_by_role("combobox", name="Letter case")
        case.click()
        page.get_by_role("option", name="Ignore case").click()
        expect(case).to_have_text("Ignore case")
        threshold = page.get_by_role("textbox", name="Threshold").first
        threshold.fill("loose")
        threshold.press("Enter")
        context_chars = page.get_by_role("spinbutton", name="Context around a match")
        context_chars.fill("150")
        context_chars.press("Tab")
        page.reload()
        page.get_by_role("tab", name="Search").click()
        expect(page.get_by_role("combobox", name="Default search engine")).to_have_text(
            "Contains (like)"
        )
        expect(page.get_by_role("combobox", name="Letter case")).to_have_text("Ignore case")
        expect(page.get_by_role("spinbutton", name="Context around a match")).to_have_value("150")
        shot(page, out, "settings-search-changed")
        for name in ("Default search engine", "Letter case", "Context around a match"):
            page.get_by_role("button", name=f"Reset to default: {name}").click()
        expect(page.get_by_role("combobox", name="Default search engine")).to_have_text(
            "All engines"
        )
        expect(page.get_by_role("spinbutton", name="Context around a match")).to_have_value("80")

        # Indexing settings: change, persist across a reload, show errors, reset.
        page.get_by_role("tab", name="Settings").click()
        page.get_by_role("tab", name="Indexing").last.click()
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
        page.get_by_role("tab", name="Indexing").last.click()
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
        page.get_by_role("tab", name="Indexing").last.click()
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

        # General: the data folder is set by VETHUQ_HOME here, so it is locked; backups can change.
        page.get_by_role("tab", name="General").click()
        data = page.get_by_test_id("setting-location.data")
        expect(data).to_contain_text("VETHUQ_HOME")
        expect(data.get_by_role("button", name="Change…")).to_be_disabled()
        backups = page.get_by_test_id("setting-location.backups")
        backups.get_by_role("button", name="Change…").click()
        folder = os.path.join(tempfile.mkdtemp(prefix="vethuq-backups-"), "kept")
        page.get_by_role("dialog").get_by_role("textbox", name="Folder").fill(folder)
        shot(page, out, "settings-backups-dialog")
        page.get_by_role("dialog").get_by_role("button", name="Change folder").click()
        expect(page.get_by_test_id("path-location.backups")).to_contain_text("kept")
        backups.get_by_role("button", name="Use the default folder").click()
        page.get_by_role("dialog").get_by_role("button", name="Use the default folder").click()
        expect(page.get_by_test_id("path-location.backups")).to_contain_text("backups")
        expect(page.get_by_role("heading", name="Data")).to_be_visible()
        shot(page, out, "settings-general-data")

        # Sources: retention in minutes, with a readable duration.
        page.get_by_role("tab", name="Sources").last.click()
        expect(page.get_by_text("7 days", exact=True)).to_be_visible()
        retention = page.get_by_role("spinbutton", name="Keep a removed source for")
        retention.fill("120")
        retention.press("Enter")
        expect(page.get_by_text("2 hours", exact=True)).to_be_visible()
        shot(page, out, "settings-sources")
        page.get_by_role("button", name="Reset to default: Keep a removed source for").click()
        expect(page.get_by_text("7 days", exact=True)).to_be_visible()

        # Processing: tiers and the hybrid options.
        page.get_by_role("tab", name="Cloud OCR").click()
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
        page.get_by_role("tab", name="Logs and database").click()
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
        page.get_by_role("tab", name="Logs and database").click()
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

        # Add-ons: none of the installed ones has settings here.
        page.get_by_role("tab", name="Add-ons").click()
        expect(page.get_by_text("None of the installed add-ons has settings.")).to_be_visible()
        shot(page, out, "settings-addons")

        # About: the support information is copied, without folders.
        page.get_by_role("tab", name="About").click()
        page.get_by_role("button", name="Copy support information").click()
        expect(page.get_by_role("button", name="Copied to the clipboard")).to_be_visible()
        copied = page.evaluate("navigator.clipboard.readText()")
        assert copied.startswith("## VethuQ support information"), copied[:80]
        assert "### Add-ons" in copied and "### Interface" in copied
        assert "- Data folder: env" in copied
        assert os.environ.get("VETHUQ_HOME", "no-such-folder") not in copied
        (out / "support-information.txt").write_text(copied, encoding="utf-8")
        shot(page, out, "about-copied")

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


def make_documents() -> Path:
    """A folder of plain text, CSV and Markdown files: enough of them for a run to take a moment."""
    root = Path(tempfile.mkdtemp(prefix="vethuq-docs-"))
    (root / "reports").mkdir()
    (root / "notes").mkdir()
    for number in range(240):
        folder = root / ("reports" if number % 2 else "notes")
        kind = ("txt", "csv", "md")[number % 3]
        body = "\n".join(
            f"line {line} of document {number}: quarterly figures" for line in range(400)
        )
        (folder / f"document-{number:03}.{kind}").write_text(body, encoding="utf-8")
    (root / "locked.bin").write_bytes(b"\x00\x01")
    return root


def sources_and_indexing(browser: Browser, out: Path) -> None:
    documents = make_documents()
    lone = Path(tempfile.mkdtemp(prefix="vethuq-lone-")) / "single.txt"
    lone.write_text("a lone file\n", encoding="utf-8")
    process, url = start_host()
    try:
        page = open_page(browser, url)
        page.get_by_role("tab", name="Sources").first.click()
        expect(page.get_by_text("No sources yet")).to_be_visible()
        shot(page, out, "sources-empty")

        # Without a native picker the path is typed.
        page.get_by_role("button", name="Add folder").click()
        page.get_by_label("Path of the folder").fill(str(documents))
        page.get_by_role("button", name="Add", exact=True).click()
        expect(page.get_by_text(f"Added {documents.name}").first).to_be_visible()
        page.wait_for_timeout(800)  # the first dialog finishes closing
        page.get_by_role("button", name="Add file").click()
        page.get_by_label("Path of the file").fill(str(lone))
        page.get_by_role("button", name="Add", exact=True).click()
        expect(page.get_by_text("Added single.txt").first).to_be_visible()
        row = page.get_by_role("row").filter(has_text=documents.name)
        expect(row).to_be_visible()
        row.click()
        shot(page, out, "sources-list")

        # The right-click menu.
        row.click(button="right")
        expect(page.get_by_role("menuitem", name="Reindex everything")).to_be_visible()
        shot(page, out, "sources-menu")
        page.keyboard.press("Escape")

        # Index the folder, then pause it part-way to look at the status bar.
        page.get_by_role("button", name="Index selected").first.click()
        expect(
            page.get_by_test_id("status-bar").get_by_text("Indexing", exact=True)
        ).to_be_visible()
        bar = page.get_by_test_id("status-bar")
        bar.get_by_role("button", name="Pause").click()
        expect(bar.get_by_text("Paused:")).to_be_visible(timeout=20000)
        shot(page, out, "status-bar-paused")
        bar.get_by_role("button", name="Resume").click()
        page.get_by_role("tab", name="Indexing").first.click()
        expect(page.get_by_text("Running in this application")).to_be_visible()
        shot(page, out, "indexing-activity")

        # Stopping asks first.
        bar.get_by_role("button", name="Stop").click()
        expect(page.get_by_text("Stop indexing?")).to_be_visible()
        shot(page, out, "stop-confirm")
        page.get_by_role("button", name="Keep going").click()

        # Let it finish.
        expect(page.get_by_text("Indexing finished").first).to_be_visible(timeout=120000)
        shot(page, out, "indexing-finished-toast")
        page.get_by_role("tab", name="History").click()
        expect(page.get_by_role("table", name="History")).to_be_visible()
        shot(page, out, "indexing-history")
        for tab in ("Remote jobs", "Queue"):
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(300)
        shot(page, out, "indexing-queue")

        # Search: the words are in every file, so narrow by type and look at the menu.
        page.get_by_role("tab", name="Search").first.click()
        box = page.get_by_role("searchbox", name="Search text")
        box.fill("document 7")
        page.get_by_role("combobox", name="File types").click()
        page.get_by_role("menuitemcheckbox", name="CSV").click()
        page.get_by_role("menuitemcheckbox", name="TXT").click()
        page.keyboard.press("Escape")
        page.get_by_role("combobox", name="Engine").click()
        page.get_by_role("option", name=re.compile("Contains")).click()
        box.press("Enter")
        expect(page.get_by_role("table", name="Search results")).to_be_visible(timeout=60000)
        page.wait_for_timeout(600)
        shot(page, out, "search-results")
        page.get_by_role("table", name="Search results").get_by_role("row").nth(3).click(
            button="right"
        )
        expect(page.get_by_role("menuitem", name="Copy path")).to_be_visible()
        shot(page, out, "search-context-menu")
        page.keyboard.press("Escape")
        page.get_by_role("button", name="Search options").click()
        expect(page.get_by_text("What counts as the same character")).to_be_visible()
        shot(page, out, "search-options")
        page.keyboard.press("Escape")
        # The files of the source: their type and status.
        page.get_by_role("tab", name="Sources").first.click()
        page.get_by_role("row").filter(has_text=documents.name).dblclick()
        table = page.get_by_role("table", name="Files")
        expect(table).to_be_visible()
        expect(table.get_by_text("document-000.txt").first).to_be_visible()
        shot(page, out, "source-files")
        page.get_by_role("combobox", name="File type").click()
        page.get_by_role("option", name="csv").click()
        page.wait_for_timeout(500)
        shot(page, out, "source-files-filtered")
        print("sources and indexing checks passed")
    finally:
        process.terminate()
        process.wait(timeout=10)


def seed_credits(home: str, documents: Path) -> None:
    """Add a source and some past OCR charges to a throw-away data folder, so the Credits pages
    have something to show. (Temporary: it writes ledger rows through the core's private models.)"""
    from datetime import UTC, datetime, timedelta

    from vethuq import VethuQ
    from vethuq._db import _CreditGrant, _CreditLedger, _IndexRun, _UsageDaily
    from vethuq._db.values import _GrantKind, _LedgerKind

    os.environ["VETHUQ_HOME"] = home
    with VethuQ() as client:
        client.credits.balance()
        client.metrics.opt_in()  # so there is something waiting to be shown
        spent_today = 0
        source = client.sources.create(documents)
        now = datetime.now(UTC)
        with client._db().session() as session:
            for day in range(14):
                when = (now - timedelta(days=day)).isoformat()
                for page in range(1, 4 + (day * 7) % 9):
                    name = (
                        documents
                        / ("reports" if day % 2 else "notes")
                        / f"document-{(day * 3 + page) % 9:03}.txt"
                    )
                    if day == 0:
                        spent_today += 1000 if page % 3 else 250
                    session.add(
                        _CreditLedger(
                            at=when,
                            wallet="local",
                            kind=_LedgerKind.CHARGE,
                            amount_milli=1000 if page % 3 else 250,
                            source_id=source.id,
                            run_id=day + 1,
                            page_number=page,
                            phase="quick",
                            language="en",
                            note=str(name),
                        )
                    )
            from vethuq.enums import IndexRunStatus

            for day in range(5):
                started = (now - timedelta(days=day)).isoformat()
                session.add(
                    _IndexRun(
                        source_id=source.id,
                        status=IndexRunStatus.COMPLETED,
                        total_files=12,
                        processed_files=12,
                        processed_pages=40,
                        ocr_pages=9 - day,
                        credits_milli=(9 - day) * 1000,
                        workers=2,
                        started_at=started,
                        completed_at=started,
                    )
                )
            # What statistics show: native pages and OCR pages by day, language, engine and band.
            for day in range(20):
                when = (now - timedelta(days=day)).date().isoformat()
                for kind, ext, language, engine, band, pages in (
                    ("native", "txt", "en", "", "", 30 + day * 3),
                    ("native", "csv", "en", "", "", 12 + day),
                    ("ocr", "pdf", "en", "rapidocr", "high", 9 - day % 5),
                    ("ocr", "pdf", "ta", "rapidocr", "medium", 3 + day % 4),
                    ("ocr", "png", "en", "paddleocr", "low", 1 + day % 3),
                ):
                    ocr = kind == "ocr"
                    session.add(
                        _UsageDaily(
                            day=when,
                            source_id=source.id,
                            file_type=ext,
                            phase="quick" if ocr else "",
                            language=language,
                            engine=engine,
                            page_source=kind,
                            size_bucket="a4",
                            band=band,
                            pages=pages,
                            passes=pages if ocr else 0,
                            duration_ms=pages * 9000 if ocr else 0,
                            confidence_sum=pages
                            * {"high": 0.95, "medium": 0.78, "low": 0.55}.get(band, 0),
                            credits_milli=pages * 1000 if ocr else 0,
                        )
                    )
            # Today's charges come out of today's allowance, as a real run would take them.
            daily = (
                session.query(_CreditGrant).filter_by(wallet="local", kind=_GrantKind.DAILY).one()
            )
            daily.remaining_milli -= spent_today


def github_fixtures(page: Page) -> None:
    """Answer the GitHub endpoints with a set-up runner and jobs (the add-on is not installed)."""
    runner = {
        "owner": "me",
        "repo": "vethuq-runner",
        "private": True,
        "workflow_ref": "v1",
        "image": "ghcr.io/vethuq/worker:1",
        "protocol": 1,
        "key_fingerprint": "9f3a-c21e",
        "set_up_at": "2026-10-01T10:00:00+00:00",
        "url": "https://github.com/me/vethuq-runner",
    }
    jobs = [
        {
            "id": 4,
            "run_id": 5,
            "tier": "github",
            "status": "completed",
            "images": 18,
            "size_bytes": 5_400_000,
            "credits": 18,
            "submitted_at": "2026-10-12T09:00:00+00:00",
            "completed_at": "2026-10-12T09:06:00+00:00",
            "error": None,
        },
        {
            "id": 3,
            "run_id": 4,
            "tier": "github",
            "status": "submitted",
            "images": 40,
            "size_bytes": 12_000_000,
            "credits": 40,
            "submitted_at": "2026-10-12T10:00:00+00:00",
            "completed_at": None,
            "error": None,
        },
        {
            "id": 2,
            "run_id": 3,
            "tier": "github",
            "status": "failed",
            "images": 7,
            "size_bytes": 900_000,
            "credits": 0,
            "submitted_at": "2026-10-11T10:00:00+00:00",
            "completed_at": None,
            "error": "The job timed out.",
        },
    ]
    answers = {
        "/api/github": {
            "installed": True,
            "enabled": True,
            "reason": "",
            "token": {
                "environment": False,
                "session": False,
                "stored": True,
                "store_available": True,
            },
            "runner": runner,
            "versions": [{"workflow_ref": "v1", "status": "current"}],
            "tier": {"id": "github", "available": True, "reason": ""},
        },
        "/api/github/availability": {"installed": True, "enabled": True, "reason": ""},
        "/api/github/jobs": {"jobs": jobs},
    }

    def handle(route):
        path = route.request.url.split("/api", 1)[1].split("?")[0]
        route.fulfill(json=answers.get("/api" + path, {}))

    page.route("**/api/github**", handle)


def credits_screens(browser: Browser, out: Path) -> None:
    documents = make_documents()
    home = tempfile.mkdtemp(prefix="vethuq-ui-")
    seed_credits(home, documents)
    process, url = start_host({**os.environ, "VETHUQ_HOME": home})
    try:
        page = open_page(browser, url)
        expect(page.get_by_test_id("credits-status")).to_contain_text("credits left today")
        shot(page, out, "credits-status-bar")
        page.get_by_test_id("credits-status").click()
        expect(page.get_by_text("Today's allowance")).to_be_visible()
        shot(page, out, "credits-overview")
        page.get_by_role("tab", name="Credits held").click()
        expect(page.get_by_role("table", name="Grants")).to_be_visible()
        shot(page, out, "credits-held")
        page.get_by_role("tab", name="Usage by day").click()
        expect(page.get_by_role("img", name="Credits spent per day")).to_be_visible()
        shot(page, out, "credits-by-day")
        page.get_by_role("tab", name="Usage by source").click()
        page.get_by_text(documents.name).first.click()
        expect(page.get_by_role("table", name="Credits per file")).to_be_visible()
        shot(page, out, "credits-by-file")
        page.get_by_role("tab", name="Ledger").click()
        expect(page.get_by_role("table", name="Ledger")).to_be_visible()
        page.wait_for_timeout(500)
        shot(page, out, "credits-ledger")
        # OCR in settings: engines, phases and models (nothing is downloaded here).
        page.get_by_role("tab", name="Settings").click()
        page.get_by_role("tab", name="OCR", exact=True).click()
        expect(page.get_by_role("table", name="OCR models")).to_be_visible()
        page.wait_for_timeout(400)
        shot(page, out, "settings-ocr")
        page.get_by_role("button", name="Remove models nothing uses").click()
        expect(page.get_by_text("Remove models nothing uses?")).to_be_visible()
        shot(page, out, "settings-ocr-confirm")
        page.get_by_role("button", name="Cancel").click()
        # Add-ons: installed, turn one off, and the bundles that can be added.
        page.get_by_role("tab", name="Add-ons").first.click()
        expect(page.get_by_role("table", name="Installed add-ons")).to_be_visible()
        page.get_by_role("switch", name="Turn csv on or off").click()
        expect(page.get_by_text("Restart VethuQ for the changes to take effect.")).to_be_visible()
        page.wait_for_timeout(400)
        shot(page, out, "addons-installed")
        page.get_by_role("tab", name="Get more").click()
        expect(page.get_by_role("table", name="Add-on bundles")).to_be_visible()
        shot(page, out, "addons-get-more")
        page.get_by_role("button", name="Install images").click()
        expect(page.get_by_text("Install images?")).to_be_visible()
        shot(page, out, "addons-install-confirm")
        page.get_by_role("button", name="Cancel").click()
        # Put the add-on back on, so the next checks see what they expect.
        page.get_by_role("tab", name="Installed").click()
        page.get_by_role("switch", name="Turn csv on or off").click()
        # Logs: a real one (this run's own), filtered, with the follow switch on.
        page.get_by_role("tab", name="Logs").first.click()
        expect(page.get_by_role("log", name="Log entries")).to_be_visible()
        page.wait_for_timeout(600)
        shot(page, out, "logs")
        page.get_by_role("combobox", name="Level").click()
        page.get_by_role("option", name="Warnings and errors").click()
        page.wait_for_timeout(500)
        page.get_by_role("button", name="Follow new entries").click()
        page.wait_for_timeout(500)
        shot(page, out, "logs-filtered-following")
        # Settings: the maintenance panels beside the settings they belong with.
        page.get_by_role("tab", name="Settings").click()
        page.get_by_role("tab", name="Logs and database").click()
        page.get_by_role("button", name="Quick check").click()
        expect(page.get_by_text("No problems found")).to_be_visible(timeout=20000)
        shot(page, out, "settings-database-check")
        page.get_by_role("tab", name="General", exact=True).click()
        expect(page.get_by_role("heading", name="Updates")).to_be_visible()
        page.get_by_role("heading", name="Updates").scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shot(page, out, "settings-updates")
        page.get_by_role("heading", name="What is shared").scroll_into_view_if_needed()
        page.get_by_role("button", name=re.compile(r"\d{4}-\d\d-\d\d · \d+ pages")).first.click()
        page.wait_for_timeout(400)
        shot(page, out, "settings-metrics-preview")
        page.get_by_role("switch", name="Show the raw data").click()
        page.get_by_label("Raw batch").scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shot(page, out, "settings-metrics-raw")
        page.get_by_role("tab", name="Search", exact=True).click()
        expect(page.get_by_role("heading", name="Search index")).to_be_visible()
        page.get_by_role("heading", name="Search index").scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        shot(page, out, "settings-search-index")
        page.get_by_role("tab", name="Cloud OCR").click()
        expect(page.get_by_role("table", name="Processing tiers")).to_be_visible()
        shot(page, out, "settings-tiers")
        page.get_by_role("tab", name="Policy").click()
        expect(page.get_by_role("heading", name="Signed policy")).to_be_visible()
        shot(page, out, "settings-policy")
        # GitHub: its add-on is not installed here, so the answers are made up for the picture.
        github_fixtures(page)
        page.goto(page.url.split("#")[0] + "#/github")
        expect(page.get_by_role("link", name="me/vethuq-runner")).to_be_visible()
        shot(page, out, "github-runner")
        page.get_by_role("tab", name="Jobs").click()
        expect(page.get_by_role("table", name="GitHub jobs")).to_be_visible()
        shot(page, out, "github-jobs")
        page.unroute("**/api/github**")
        # Statistics.
        page.get_by_role("tab", name="Statistics").first.click()
        expect(page.get_by_text("Pages read", exact=True)).to_be_visible()
        page.wait_for_timeout(500)
        shot(page, out, "stats-summary")
        page.get_by_role("tab", name="Breakdown").click()
        expect(page.get_by_role("table", name="Breakdown")).to_be_visible()
        page.wait_for_timeout(400)
        shot(page, out, "stats-breakdown")
        page.get_by_role("combobox", name="Group by").click()
        page.get_by_role("option", name="Language").click()
        page.get_by_role("table", name="Breakdown").get_by_text("ta", exact=True).click()
        page.wait_for_timeout(600)
        shot(page, out, "stats-narrowed")
        # The cost on the other pages.
        page.get_by_role("tab", name="Sources").first.click()
        expect(page.get_by_role("columnheader", name="Credits")).to_be_visible()
        shot(page, out, "sources-credits")
        page.get_by_role("row").filter(has_text=documents.name).dblclick()
        expect(page.get_by_role("table", name="Files")).to_be_visible()
        page.wait_for_timeout(500)
        shot(page, out, "source-files-credits")
        page.get_by_role("tab", name="Indexing").first.click()
        page.get_by_role("tab", name="History").click()
        expect(page.get_by_role("table", name="History")).to_be_visible()
        shot(page, out, "indexing-history-credits")
        page.get_by_role("tab", name="Credits").first.click()
        page.get_by_role("button", name="Redeem a licence").click()
        expect(page.get_by_placeholder("Paste the licence text")).to_be_visible()
        page.get_by_placeholder("Paste the licence text").fill("not a licence")
        page.get_by_role("button", name="Redeem", exact=True).click()
        page.wait_for_timeout(800)
        shot(page, out, "credits-redeem-refused")
        print("credits checks passed")
    finally:
        process.terminate()
        process.wait(timeout=10)


def make_pdf(path: Path, pages: list[list[str]]) -> None:
    """A small PDF, one text object per line, built by hand (no PDF library needed)."""
    objects: list[bytes] = []
    kids = " ".join(f"{3 + 2 * n} 0 R" for n in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font = 3 + 2 * len(pages)
    for number, lines in enumerate(pages):
        content = ["BT /F1 16 Tf 60 740 Td 22 TL"]
        for line in lines:
            content.append(f"({line}) Tj T*")
        content.append("ET")
        stream = "\n".join(content).encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * number} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode()
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    )
    path.write_bytes(bytes(out))


def preview_screens(browser: Browser, out: Path) -> None:
    from vethuq import VethuQ

    documents = Path(tempfile.mkdtemp(prefix="vethuq-pdf-"))
    filler = ["Quarterly review", "Nothing about grain on this page.", "More filler text here."]
    make_pdf(
        documents / "harvest-report.pdf",
        [
            ["Harvest report", *filler],
            ["Prices", "The price of wheat rose sharply in autumn.", "Barley stayed flat."],
            ["Stocks", *filler],
            ["Outlook", "Next year wheat is expected to recover.", "Rain is the main risk."],
        ],
    )
    # A long text with one rare word deep inside it.
    (documents / "field-notes.txt").write_text(
        "\n".join(
            f"{n:>6} daily note about the {'zebra' if n == 45123 else 'weather'} on the farm"
            for n in range(1, 60001)
        ),
        encoding="utf-8",
    )
    # A long table, with one rare name in it.
    people = ["id,name,city,balance"]
    for n in range(1, 5001):
        name = "Quillon Zephyr" if n == 2345 else f"Person {n:04}"
        people.append(f"{n},{name},{('Paris', 'Oslo', 'Lima', 'Pune')[n % 4]},{(n * 37) % 1000}.50")
    (documents / "people.csv").write_text("\n".join(people), encoding="utf-8")
    # A long handbook (about 3 MB of Markdown) with one rare word deep inside it.
    parts = ["# Farm handbook", ""]
    for n in range(1, 20001):
        if n % 500 == 1:
            parts += [f"## Chapter {n // 500 + 1}", ""]
        word = "**quokka**" if n == 15000 else "barley"
        parts += [
            f"Paragraph {n}: notes on the {word} and the *weather* in [the valley](http://x.test/{n}).",
            "",
        ]
    (documents / "handbook.md").write_text("\n".join(parts), encoding="utf-8")
    home = tempfile.mkdtemp(prefix="vethuq-ui-")
    os.environ["VETHUQ_HOME"] = home
    with VethuQ() as client:
        client.settings.index.set_stability_check_seconds(0)
        client.sources.create(documents)
        client.index.run()
    process, url = start_host({**os.environ, "VETHUQ_HOME": home})
    try:
        page = open_page(browser, url)
        page.get_by_role("tab", name="Search").first.click()
        box = page.get_by_role("searchbox", name="Search text")
        box.fill("wheat")
        page.get_by_role("combobox", name="Engine").click()
        page.get_by_role("option", name=re.compile("Contains")).click()
        box.press("Enter")
        table = page.get_by_role("table", name="Search results")
        expect(table).to_be_visible(timeout=60000)
        table.get_by_text("2 of 4").first.click(button="right")
        page.get_by_role("menuitem", name="Preview").click()
        panel = page.get_by_role("region", name="PDF preview")
        expect(panel.get_by_text(re.compile("Match 1 of 2"))).to_be_visible()
        expect(panel.locator("canvas").first).to_be_visible(timeout=30000)
        page.wait_for_timeout(4000)
        shot(page, out, "preview-first-match")
        panel.get_by_role("button", name="Next match").click()
        expect(panel.get_by_text(re.compile("Match 2 of 2"))).to_be_visible()
        page.wait_for_timeout(1500)
        shot(page, out, "preview-second-match")
        marked = page.evaluate(
            "() => [...document.querySelectorAll('.pdf-text-layer span')]"
            ".filter(s => getComputedStyle(s).backgroundColor.startsWith('rgba(255, 196'))"
            ".map(s => s.textContent)"
        )
        print("marked:", marked)
        assert any("wheat" in text for text in marked), marked
        # The text preview: a rare word deep in a long text.
        box.fill("zebra")
        box.press("Enter")
        expect(table.get_by_text("field-notes.txt").first).to_be_visible(timeout=60000)
        table.get_by_text("1 of 1").first.click(button="right")
        page.get_by_role("menuitem", name="Preview").click()
        text = page.get_by_role("region", name="Text preview")
        expect(text.get_by_text(re.compile("line 45123"))).to_be_visible()
        expect(text.locator("mark")).to_have_text("zebra")
        page.wait_for_timeout(800)
        shot(page, out, "preview-text")
        top = text.get_by_role("table").evaluate("e => e.scrollTop")
        assert top > 900000, top
        # The table preview: the matching cell in a long table, then sort and filter.
        box.fill("Quillon")
        box.press("Enter")
        expect(table.get_by_text("people.csv").first).to_be_visible(timeout=60000)
        table.get_by_text("1 of 1").first.click(button="right")
        page.get_by_role("menuitem", name="Preview").click()
        grid = page.get_by_role("region", name="Table preview")
        expect(grid.locator("mark")).to_have_text("Quillon")
        page.wait_for_timeout(800)
        shot(page, out, "preview-table")
        grid.get_by_role("button", name=re.compile("^name")).click()
        grid.get_by_role("button", name=re.compile("^name")).click()
        grid.get_by_role("textbox", name="Filter rows").fill("pune")
        page.wait_for_timeout(1200)
        expect(grid.get_by_text(re.compile(r"of 5,000 rows"))).to_be_visible()
        shot(page, out, "preview-table-sorted-filtered")
        # The Markdown preview: a rare word deep in a long, rendered document.
        box.fill("quokka")
        box.press("Enter")
        expect(table.get_by_text("handbook.md").first).to_be_visible(timeout=120000)
        table.get_by_text("1 of 1").first.click(button="right")
        page.get_by_role("menuitem", name="Preview").click()
        doc = page.get_by_role("region", name="Markdown preview")
        expect(doc.locator("mark")).to_have_text("quokka", timeout=30000)
        page.wait_for_timeout(800)
        shot(page, out, "preview-markdown")
        assert doc.locator("[data-block]").count() < 2000, (
            "only the blocks near the screen are drawn"
        )
        doc.get_by_role("tab", name="Source").click()
        expect(doc.locator("mark")).to_contain_text("quokka", timeout=30000)
        shot(page, out, "preview-markdown-source")
        print("preview checks passed")
    finally:
        process.terminate()
        process.wait(timeout=10)


SAMPLE_CSS = """/* Farm site: base styles */
:root {
  --green: #2e7d32;
  --gap: 1.25rem;
}

@import url("fonts.css");
@charset "utf-8";

html, body {
  margin: 0;
  font: 16px/1.5 "Segoe UI", system-ui, sans-serif;
  background: #fafafa url(img/paper.png) repeat;
}

.card > .title:hover,
a[href^="http"]::after {
  color: var(--green);
  padding: calc(var(--gap) * 2) 0.5em !important;
  transition: color 0.2s ease-in-out, transform 150ms;
}

@media (min-width: 600px) and (max-width: 900px) {
  .grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    /* three columns on tablets */
    gap: var(--gap);
  }
  .grid .quokka { opacity: .85; }
}

@font-face {
  font-family: "Farm Sans";
  src: url(fonts/farm.woff2) format("woff2");
}

@keyframes grow {
  from { transform: scale(1); }
  50% { transform: scale(1.08); }
  to { transform: scale(1); }
}
"""


def css_preview_screens(browser: Browser, out: Path) -> None:
    """The CSS preview. The css add-on is licensed code, so the search result and the file are
    answered by the test itself; what is shown is the interface's own work."""
    documents = Path(tempfile.mkdtemp(prefix="vethuq-css-"))
    (documents / "readme.txt").write_text("quokka", encoding="utf-8")
    minified = re.sub(r"/\*.*?\*/", "", SAMPLE_CSS, flags=re.S)
    minified = re.sub(r"\s+", " ", minified).replace("{ ", "{").replace("; ", ";") * 40
    for theme, name in (("light", "css-light"), ("dark", "css-dark")):
        home = tempfile.mkdtemp(prefix="vethuq-ui-")
        process, url = start_host({**os.environ, "VETHUQ_HOME": home})
        try:
            context = browser.new_context(viewport=VIEWPORT, color_scheme=theme)
            context.add_init_script(f"localStorage.setItem('vethuq.theme', '{theme}')")
            page = context.new_page()
            page.goto(url)
            expect(page.get_by_test_id("app-shell")).to_be_visible()

            def run(route):
                route.fulfill(
                    json={
                        "query": "quokka",
                        "engine": "like",
                        "total": 1,
                        "levels": {},
                        "index_rebuilt": False,
                        "pending": {},
                        "options": {},
                        "matches": [
                            {
                                "file_id": 1,
                                "document_id": 1,
                                "file_name": "site.css",
                                "file_path": "/x/site.css",
                                "file_type": "css",
                                "page_number": 1,
                                "total_pages": 1,
                                "before": "} @media (min-width: 600px) and "
                                "(max-width: 900px) { .grid { display: grid; gap: var(--gap); } "
                                ".grid .",
                                "matched": "quokka",
                                "after": " { opacity: .85; } }",
                                "truncated_before": True,
                                "truncated_after": False,
                                "duplicate_of_path": None,
                                "source": "native",
                                "score": None,
                                "start": 10,
                                "end": 16,
                                "engine": "like",
                                "matched_by": ["like"],
                                "modifiers": [],
                            }
                        ],
                    }
                )

            page.route("**/api/search/run", run)
            page.route(
                "**/api/files/css**",
                lambda route: route.fulfill(
                    json={
                        "text": SAMPLE_CSS if "min" not in route.request.url else minified,
                        "encoding": "utf-8",
                        "file_name": "site.css",
                        "longest_line": 90,
                    }
                ),
            )
            page.get_by_role("tab", name="Search").first.click()
            box = page.get_by_role("searchbox", name="Search text")
            box.fill("quokka")
            box.press("Enter")
            table = page.get_by_role("table", name="Search results")
            expect(table).to_be_visible(timeout=30000)
            table.get_by_text("1 of 1").first.click(button="right")
            page.get_by_role("menuitem", name="Preview").click()
            code = page.get_by_role("region", name="Code preview")
            expect(code.locator("mark")).to_have_text("quokka", timeout=30000)
            page.wait_for_timeout(600)
            shot(page, out, name)
            context.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
    print("css preview checks passed")


SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Farm news</title>
<style>
  body { font-family: Georgia, serif; margin: 2rem; color: #333; }
  h1 { color: #2e7d32; border-bottom: 2px solid #2e7d32; }
  .note { background: #fff8e1; padding: 1rem; border-left: 4px solid #f9a825; }
</style>
<script>document.body.insertAdjacentHTML('beforeend', '<p id="ran">SCRIPT RAN</p>');</script>
</head>
<body>
<h1>Harvest report</h1>
<p>Prices of <b>wheat</b> and barley rose in autumn &amp; the quokka population grew.</p>
<div class="note">Read the <a href="http://example.invalid/more">full story</a>.</div>
<img src="http://example.invalid/field.png" alt="a field in autumn">
<!-- a hidden comment about the quokka -->
</body>
</html>
"""


def html_preview_screens(browser: Browser, out: Path) -> None:
    """The web page preview, with the search result and the file answered by the test (the html
    add-on is licensed code). Checks that nothing in the page runs or reaches the network."""
    requested: list[str] = []
    failed: list[tuple[str, str | None]] = []
    finished: list[str] = []
    for theme, name in (("light", "html-rendered"), ("dark", "html-source-dark")):
        home = tempfile.mkdtemp(prefix="vethuq-ui-")
        process, url = start_host({**os.environ, "VETHUQ_HOME": home})
        try:
            context = browser.new_context(viewport=VIEWPORT, color_scheme=theme)
            context.add_init_script(f"localStorage.setItem('vethuq.theme', '{theme}')")
            page = context.new_page()
            page.on("request", lambda r: requested.append(r.url))
            page.on("requestfailed", lambda r: failed.append((r.url, r.failure)))
            page.on("requestfinished", lambda r: finished.append(r.url))
            page.goto(url)
            expect(page.get_by_test_id("app-shell")).to_be_visible()
            match = {
                "file_id": 1,
                "document_id": 1,
                "file_name": "news.html",
                "file_path": "/x/news.html",
                "file_type": "html",
                "page_number": 1,
                "total_pages": 1,
                "before": "Harvest report Prices of wheat and barley rose in autumn & the ",
                "matched": "quokka",
                "after": " population grew.",
                "truncated_before": False,
                "truncated_after": False,
                "duplicate_of_path": None,
                "source": "native",
                "score": None,
                "start": 60,
                "end": 66,
                "engine": "like",
                "matched_by": ["like"],
                "modifiers": [],
            }
            page.route(
                "**/api/search/run",
                lambda route, _request, match=match: route.fulfill(
                    json={
                        "query": "quokka",
                        "engine": "like",
                        "total": 1,
                        "levels": {},
                        "index_rebuilt": False,
                        "pending": {},
                        "options": {},
                        "matches": [match],
                    }
                ),
            )
            page.route(
                "**/api/files/html**",
                lambda route: route.fulfill(
                    json={"text": SAMPLE_HTML, "encoding": "utf-8", "file_name": "news.html"}
                ),
            )
            page.get_by_role("tab", name="Search").first.click()
            box = page.get_by_role("searchbox", name="Search text")
            box.fill("quokka")
            box.press("Enter")
            table = page.get_by_role("table", name="Search results")
            expect(table).to_be_visible(timeout=30000)
            table.get_by_text("1 of 1").first.click(button="right")
            page.get_by_role("menuitem", name="Preview").click()
            panel = page.get_by_role("region", name="Web page preview")
            if theme == "light":
                frame = page.frame_locator("iframe[title='Rendered page']")
                expect(frame.locator("mark")).to_have_text("quokka", timeout=30000)
                expect(frame.get_by_role("heading", name="Harvest report")).to_be_visible()
                assert frame.locator("#ran").count() == 0, "a script of the page ran"
                page.wait_for_timeout(500)
                shot(page, out, name)
                frame.get_by_role("link").click()
                page.wait_for_timeout(500)
                outside = [u for u in requested if "example.invalid" in u]
                print("outside requests:", outside, [f for f in failed if "invalid" in f[0]])
                assert not any("example.invalid" in u for u in finished), finished
                assert all(
                    any(u == f[0] and "csp" in (f[1] or "") for f in failed) for u in outside
                ), failed
            else:
                panel.get_by_role("tab", name="Source").click()
                expect(panel.locator("mark")).to_have_text("quokka", timeout=30000)
                page.wait_for_timeout(500)
                shot(page, out, name)
            context.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
    print("html preview checks passed")


CODE_SAMPLES = {
    "json": (
        "dark",
        '{"name":"farm-api","version":"1.4.2","private":true,"scripts":{"start":"node server.js",'
        '"test":"vitest run"},"ports":[8080,8081],"limits":{"rate":0.5,"burst":20,"note":null},'
        '"owner":{"port":8080,"name":"Ada \\"Quokka\\" Lovelace"}}',
        {
            "before": 'owner.port: 8080 owner.name: Ada "',
            "matched": "Quokka",
            "after": '" Lovelace',
        },
    ),
    "yaml": (
        "light",
        "# Farm service\nversion: 3\nservices:\n  web:\n    image: farm/web:1.4\n    ports:\n"
        '      - "8080:80"\n    environment: &env\n      DEBUG: yes\n      RATE: 0.5\n'
        "  worker:\n    environment: *env\n    command: |\n      run --queue quokka\n"
        "      --retries 3\n",
        {
            "before": "services.worker.command: run --queue ",
            "matched": "quokka",
            "after": " --retries 3",
        },
    ),
    "js": (
        "dark",
        "#!/usr/bin/env node\nimport { readFile } from 'node:fs/promises';\n\n"
        "/** Count the quokka in a log. */\n"
        "export async function count(path, word = /quokka/gi) {\n"
        "  const text = await readFile(path, 'utf8');\n  const hits = text.match(word) ?? [];\n"
        "  console.log(`found ${hits.length} of 100 (${(hits.length / 100) * 100}%)`);\n"
        "  return hits.length > 0 ? hits : null; // done\n}\n",
        {"before": "/** Count the ", "matched": "quokka", "after": " in a log. */ export async"},
    ),
    "xml": (
        "light",
        '<?xml version="1.0" encoding="UTF-8"?>\n<!-- Farm catalogue -->\n<farm:catalog '
        'xmlns:farm="urn:farm" updated="2026-10-13">\n  <animal id="q1" kind="marsupial">\n'
        "    <name>Quokka</name>\n    <note><![CDATA[ friendly <very> ]]></note>\n  </animal>\n"
        '  <animal id="b2"><name>Barley &amp; oats</name></animal>\n</farm:catalog>\n',
        {
            "before": "farm:catalog/animal@id: q1 farm:catalog/animal@kind: marsupial "
            "farm:catalog/animal/name: ",
            "matched": "Quokka",
            "after": "",
        },
    ),
}


def code_preview_screens(browser: Browser, out: Path) -> None:
    """The JSON, YAML, JavaScript and XML previews; the search result and the file are answered by
    the test (the add-ons are licensed code)."""
    for kind, (theme, text, words) in CODE_SAMPLES.items():
        home = tempfile.mkdtemp(prefix="vethuq-ui-")
        process, url = start_host({**os.environ, "VETHUQ_HOME": home})
        try:
            context = browser.new_context(viewport=VIEWPORT, color_scheme=theme)
            context.add_init_script(f"localStorage.setItem('vethuq.theme', '{theme}')")
            page = context.new_page()
            page.goto(url)
            expect(page.get_by_test_id("app-shell")).to_be_visible()
            match = {
                "file_id": 1,
                "document_id": 1,
                "file_name": f"sample.{kind}",
                "file_path": f"/x/sample.{kind}",
                "file_type": kind,
                "page_number": 1,
                "total_pages": 1,
                "truncated_before": False,
                "truncated_after": False,
                "duplicate_of_path": None,
                "source": "native",
                "score": None,
                "start": 10,
                "end": 16,
                "engine": "like",
                "matched_by": ["like"],
                "modifiers": [],
                **words,
            }
            page.route(
                "**/api/search/run",
                lambda route, _request, match=match: route.fulfill(
                    json={
                        "query": "quokka",
                        "engine": "like",
                        "total": 1,
                        "levels": {},
                        "index_rebuilt": False,
                        "pending": {},
                        "options": {},
                        "matches": [match],
                    }
                ),
            )
            longest = 5000 if kind == "json" else 90
            page.route(
                f"**/api/files/{kind}**",
                lambda route, _request, text=text, kind=kind, longest=longest: route.fulfill(
                    json={
                        "text": text,
                        "encoding": "utf-8",
                        "file_name": f"sample.{kind}",
                        "longest_line": longest,
                    }
                ),
            )
            page.get_by_role("tab", name="Search").first.click()
            box = page.get_by_role("searchbox", name="Search text")
            box.fill("quokka")
            box.press("Enter")
            table = page.get_by_role("table", name="Search results")
            expect(table).to_be_visible(timeout=30000)
            table.get_by_text("1 of 1").first.click(button="right")
            page.get_by_role("menuitem", name="Preview").click()
            code = page.get_by_role("region", name="Code preview")
            expect(code.locator("mark")).to_have_text(words["matched"], timeout=30000)
            page.wait_for_timeout(600)
            shot(page, out, f"code-{kind}")
            context.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
    print("code preview checks passed")


def sample_picture(frame: int = 1) -> bytes:
    """A picture of a scanned page: three lines of text, the second with the word to find."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    page = Image.new("RGB", (900, 600), (250, 247, 240) if frame == 1 else (235, 242, 250))
    draw = ImageDraw.Draw(page)
    try:
        font = ImageFont.load_default(size=34)
    except TypeError:
        font = ImageFont.load_default()
    draw.text((60, 60), f"Harvest report (page {frame})", fill=(30, 30, 30), font=font)
    draw.text((60, 140), "The price of wheat rose in autumn", fill=(30, 30, 30), font=font)
    draw.text((60, 220), "Barley and oats stayed flat", fill=(30, 30, 30), font=font)
    draw.line((60, 300, 840, 300), fill=(120, 120, 120), width=2)
    out = io.BytesIO()
    page.save(out, format="PNG")
    return out.getvalue()


def wheat_box() -> list[float]:
    """Where `wheat` is in `sample_picture`, as fractions of it (found by measuring the text)."""
    from PIL import ImageFont

    try:
        font = ImageFont.load_default(size=34)
    except TypeError:
        font = ImageFont.load_default()
    before = font.getlength("The price of ")
    width = font.getlength("wheat")
    return [(60 + before) / 900, 138 / 600, (60 + before + width) / 900, 184 / 600]


def picture_preview_screens(browser: Browser, out: Path) -> None:
    """The picture preview. The search result, the text window and the pictures are answered by the
    test (the picture add-ons are licensed code); the box is where `wheat` is drawn above."""
    for theme, name, kind in (
        ("light", "picture-png", "png"),
        ("dark", "picture-tiff-dark", "tiff"),
    ):
        home = tempfile.mkdtemp(prefix="vethuq-ui-")
        process, url = start_host({**os.environ, "VETHUQ_HOME": home})
        try:
            context = browser.new_context(viewport=VIEWPORT, color_scheme=theme)
            context.add_init_script(f"localStorage.setItem('vethuq.theme', '{theme}')")
            page = context.new_page()
            page.goto(url)
            expect(page.get_by_test_id("app-shell")).to_be_visible()
            lines = [
                "Harvest report (page 2)",
                "The price of wheat rose in autumn",
                "Barley and oats stayed flat",
            ]
            start = len(lines[0]) + 1 + lines[1].index("wheat")
            match = {
                "file_id": 1,
                "document_id": 1,
                "file_name": f"scan.{kind}",
                "file_path": f"/x/scan.{kind}",
                "file_type": kind,
                "page_number": 2 if kind == "tiff" else 1,
                "total_pages": 3 if kind == "tiff" else 1,
                "before": "Harvest report (page 2) The price of ",
                "matched": "wheat",
                "after": " rose in autumn",
                "truncated_before": False,
                "truncated_after": False,
                "duplicate_of_path": None,
                "source": "ocr",
                "score": None,
                "start": start,
                "end": start + 5,
                "engine": "like",
                "matched_by": ["like"],
                "modifiers": [],
                "boxes": [wheat_box()],
            }
            page.route(
                "**/api/search/run",
                lambda route, _request, match=match: route.fulfill(
                    json={
                        "query": "wheat",
                        "engine": "like",
                        "total": 1,
                        "levels": {},
                        "index_rebuilt": False,
                        "pending": {},
                        "options": {},
                        "matches": [match],
                    }
                ),
            )
            page.route(
                "**/api/files/text**",
                lambda route, _request, lines=lines: route.fulfill(
                    json={"total": len(lines), "start": 0, "lines": lines, "file_name": "scan"}
                ),
            )
            page.route(
                f"**/api/files/{kind}**",
                lambda route, request, kind=kind: route.fulfill(
                    body=sample_picture(2 if "page=2" in request.url or kind == "png" else 1),
                    content_type="image/png",
                ),
            )
            page.get_by_role("tab", name="Search").first.click()
            box = page.get_by_role("searchbox", name="Search text")
            box.fill("wheat")
            box.press("Enter")
            table = page.get_by_role("table", name="Search results")
            expect(table).to_be_visible(timeout=30000)
            table.get_by_text(re.compile(r"\d of \d")).first.click(button="right")
            page.get_by_role("menuitem", name="Preview").click()
            panel = page.get_by_role("region", name="Picture preview")
            expect(panel.locator("[data-box]")).to_be_visible(timeout=30000)
            expect(panel.locator("mark")).to_have_text("wheat")
            page.wait_for_timeout(600)
            shot(page, out, name)
            if kind == "png":
                panel.get_by_role("button", name="Turn right").click()
                panel.get_by_role("button", name="100%").click()
                page.wait_for_timeout(600)
                shot(page, out, "picture-turned-zoomed")
            context.close()
        finally:
            process.terminate()
            process.wait(timeout=10)
    print("picture preview checks passed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("shots"))
    parser.add_argument("--channel", help="browser channel to use, e.g. msedge")
    parser.add_argument("--executable", help="path to a Chromium binary")
    parser.add_argument("--only-sources", action="store_true")
    parser.add_argument("--only-credits", action="store_true")
    parser.add_argument("--only-preview", action="store_true")
    parser.add_argument("--only-css", action="store_true")
    parser.add_argument("--only-html", action="store_true")
    parser.add_argument("--only-code", action="store_true")
    parser.add_argument("--only-pictures", action="store_true")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel, executable_path=args.executable)
        try:
            if args.only_pictures:
                picture_preview_screens(browser, args.out)
                return 0
            if args.only_code:
                code_preview_screens(browser, args.out)
                return 0
            if args.only_html:
                html_preview_screens(browser, args.out)
                return 0
            if args.only_css:
                css_preview_screens(browser, args.out)
                return 0
            if args.only_preview:
                preview_screens(browser, args.out)
                return 0
            only = args.only_sources or args.only_credits
            if not only:
                run(browser, args.out)
            if not args.only_credits:
                sources_and_indexing(browser, args.out)
            if not args.only_sources:
                credits_screens(browser, args.out)
        finally:
            browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
