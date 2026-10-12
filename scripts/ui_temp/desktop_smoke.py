"""Opens the real desktop window, checks it and captures the screen (temporary, Windows)."""
# ruff: noqa: S101, S110

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from vethuq_desktop import run_desktop

SHELL = "!!document.querySelector('[data-testid=app-shell]')"
LOADED = "document.body.innerText.includes('VethuQ 0.')"


def wait_for(window: Any, expression: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if window.evaluate_js(expression):
                return
        except Exception:  # noqa: BLE001  # the page is still loading
            pass
        time.sleep(0.3)
    raise TimeoutError(f"Timed out waiting for: {expression}")


def fit_to_screen(window: Any) -> dict[str, int]:
    import ctypes

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    window.move(0, 0)
    window.resize(min(1200, width), min(780, height - 40))
    return {"screen_width": width, "screen_height": height}


def grab(out: Path, name: str) -> None:
    from PIL import ImageGrab

    time.sleep(1.0)
    ImageGrab.grab(all_screens=True).save(out / f"desktop-{name}.png")
    print("captured", name, flush=True)


def check(window: Any, out: Path, result: dict[str, Any]) -> None:
    result["screen"] = fit_to_screen(window)
    wait_for(window, SHELL)
    wait_for(window, LOADED)
    result["user_agent"] = window.evaluate_js("navigator.userAgent")
    result["platform"] = window.evaluate_js("fetch('/api/platform').then(r => r.json())")
    result["title_bar_buttons"] = window.evaluate_js(
        "[...document.querySelectorAll('[data-testid=title-bar] button')]"
        ".map(b => b.getAttribute('aria-label'))"
    )
    grab(out, "home-light")

    window.evaluate_js("document.querySelector('[aria-label=Maximize]').click()")
    time.sleep(1.5)
    result["maximized_after_click"] = window.evaluate_js(
        "fetch('/api/window/state').then(r => r.json()).then(s => s.maximized)"
    )
    grab(out, "maximized")
    window.evaluate_js("document.querySelector('[aria-label=Restore]').click()")
    time.sleep(1.5)
    result["maximized_after_restore"] = window.evaluate_js(
        "fetch('/api/window/state').then(r => r.json()).then(s => s.maximized)"
    )

    window.evaluate_js("localStorage.setItem('vethuq.theme', 'dark'); location.reload()")
    time.sleep(1.0)
    wait_for(window, SHELL)
    wait_for(window, LOADED)
    grab(out, "home-dark")
    window.evaluate_js("location.hash = '#/about'")
    wait_for(window, "document.body.innerText.includes('Database schema')")
    grab(out, "about-dark")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("shots"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"ok": False}

    def hook(window: Any) -> None:
        try:
            check(window, args.out, result)
            result["ok"] = (
                result["platform"]["window_controls"] is True
                and result["title_bar_buttons"] == ["Minimize", "Maximize", "Close"]
                and result["maximized_after_click"] is True
                and result["maximized_after_restore"] is False
            )
        except Exception:  # noqa: BLE001
            result["error"] = traceback.format_exc()
            traceback.print_exc()
        finally:
            (args.out / "desktop-result.json").write_text(json.dumps(result, indent=2))
            window.destroy()

    # If the GUI never comes up, do not hang the job.
    watchdog = threading.Timer(150, lambda: os._exit(3))
    watchdog.daemon = True
    watchdog.start()
    run_desktop(on_started=hook)
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
