"""Starts the API and shows it in a window."""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from vethuq_api import create_app
from vethuq_api.core import VethuQCore
from vethuq_desktop.server import LocalServer
from vethuq_desktop.webdist import WebDistNotFoundError, resolve_web_dist
from vethuq_desktop.window import SimulatedWindowController, WebviewWindowController

TITLE = "VethuQ"
DEFAULT_SIZE = (1200, 780)
MIN_SIZE = (900, 600)


def _bootstrap_url(server: LocalServer, token: str) -> str:
    return f"{server.origin}/?t={token}"


def run_desktop(
    *,
    web_dist: Path | None = None,
    debug: bool = False,
    on_started: Callable[[Any], None] | None = None,
) -> int:
    """Open the application window and block until it closes.

    `on_started(window)` runs on a helper thread once the GUI loop is running (tests and tooling use
    it to inspect or capture the window).
    """
    import webview  # imported here so the rest of the package works without a GUI toolkit

    token = secrets.token_urlsafe(32)
    controller = WebviewWindowController()
    core = VethuQCore()
    # A run this application started stops when it closes, so closing is held back to ask first.
    controller.close_guard = lambda: core.indexing().one_off_active()
    app = create_app(
        bootstrap_token=token,
        web_dist=resolve_web_dist(web_dist),
        window=controller,
        host_kind="desktop",
        core=core,
    )
    server = LocalServer(app)
    server.start()
    try:
        server.wait_until_ready()
        window = webview.create_window(
            TITLE,
            url=_bootstrap_url(server, token),
            width=DEFAULT_SIZE[0],
            height=DEFAULT_SIZE[1],
            min_size=MIN_SIZE,
            frameless=True,
            easy_drag=False,
        )
        controller.attach(window)
        settings = getattr(webview, "settings", None)
        if isinstance(settings, dict):
            settings["ALLOW_DOWNLOADS"] = True  # exports are saved through the system dialog
        start_options: dict[str, Any] = {"debug": debug}
        if sys.platform == "win32":
            # Never fall back to the legacy MSHTML engine.
            start_options["gui"] = "edgechromium"
        if on_started is not None:
            start_options.update(func=on_started, args=(window,))
        webview.start(**start_options)
    finally:
        server.stop()
    return 0


def run_headless(*, web_dist: Path | None = None) -> int:
    """Serve the interface without a window and print the URL to open in a browser."""
    token = secrets.token_urlsafe(32)
    controller = SimulatedWindowController()
    app = create_app(
        bootstrap_token=token,
        web_dist=resolve_web_dist(web_dist),
        window=controller,
        host_kind="desktop",
    )
    server = LocalServer(app)
    server.start()
    try:
        server.wait_until_ready()
        print(json.dumps({"url": _bootstrap_url(server, token)}), flush=True)
        try:
            while not controller.closed.wait(0.25):
                pass
        except KeyboardInterrupt:
            pass
    finally:
        server.stop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vethuq-desktop", description="The VethuQ desktop application."
    )
    parser.add_argument(
        "--no-window", action="store_true", help="serve only; print the URL to open"
    )
    parser.add_argument("--web-dist", type=Path, help="folder holding the built interface")
    parser.add_argument("--debug", action="store_true", help="enable the WebView2 developer tools")
    args = parser.parse_args(argv)
    try:
        if args.no_window:
            return run_headless(web_dist=args.web_dist)
        return run_desktop(web_dist=args.web_dist, debug=args.debug)
    except WebDistNotFoundError as error:
        print(error, file=sys.stderr)
        return 2
