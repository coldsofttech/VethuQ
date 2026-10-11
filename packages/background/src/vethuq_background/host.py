"""The service itself: works through the index queue, one request at a time.

Each request is run with `client.index.queue.run_next()`, the same `index.run(...)` a person calls,
so every setting, `index status|pause|resume|stop` and the add-ons that act on a run (backups,
adaptive workers) apply to it as to any run. The host adds the loop, its marker (so index commands
know to queue their work), and pause / resume / stop:

- a signal (SIGTERM, SIGINT, SIGBREAK) or `stop()` ends the loop after asking the run to stop;
- the control file in the data folder's `run` folder (`pause` or `run`) pauses and resumes it;
  `BackgroundService.pause()` and `resume()` write it.
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Any

import vethuq

_logger = logging.getLogger("vethuq.indexing")


class ServiceHost:
    POLL_SECONDS = 2.0  # how often an idle host looks at the queue
    CONTROL_SECONDS = 1.0  # how often it looks at the control file while a request runs

    def __init__(self, client: Any, poll: float | None = None) -> None:
        self.client = client
        self.poll = self.POLL_SECONDS if poll is None else poll
        self._stopping = threading.Event()
        self._paused = threading.Event()
        self._path = client.index.queue.control_file()
        self.worked = 0

    # ----- control ----------------------------------------------------------------------------

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def stop(self) -> None:
        """End the loop: the request being worked is asked to stop, and no other is taken."""
        self._stopping.set()
        self._ask(self.client.index.stop, wait=False)

    def pause(self) -> None:
        self._paused.set()
        self._ask(self.client.index.pause)

    def resume(self) -> None:
        self._paused.clear()
        self._ask(self.client.index.resume)

    @staticmethod
    def _ask(action: Any, **kwargs: Any) -> None:
        try:
            action(**kwargs)
        except vethuq.errors.IndexNotRunningError:
            pass  # nothing is going: the flag alone does it for the next request
        except Exception:  # noqa: BLE001 - control never takes the service down
            _logger.warning("Background service control failed", exc_info=True)

    def look_at_control_file(self) -> None:
        """Follow `pause` / `run` written by the service commands."""
        try:
            wanted = self._path.read_text(encoding="utf-8").strip()
        except OSError:
            wanted = "run"
        if wanted == "pause" and not self.paused:
            self.pause()
        elif wanted != "pause" and self.paused:
            self.resume()

    def _watch(self, over: threading.Event) -> None:
        while not over.wait(self.CONTROL_SECONDS):
            self.look_at_control_file()

    # ----- the loop ---------------------------------------------------------------------------

    def run(self, once: bool = False) -> int:
        """Work the queue until stopped (or, with `once`, until nothing is waiting). Returns how
        many requests were worked."""
        queue = self.client.index.queue
        queue.announce_service()
        over = threading.Event()
        watcher = threading.Thread(
            target=self._watch, args=(over,), name="vethuq-control", daemon=True
        )
        watcher.start()
        _logger.info("Background service started (pid %d)", os.getpid())
        try:
            while not self._stopping.is_set():
                self.look_at_control_file()
                job = None if self.paused else queue.run_next()
                if job is not None:
                    self.worked += 1
                    continue
                if once and not self.paused:
                    break
                self._stopping.wait(self.poll)
        finally:
            over.set()
            queue.clear_service()
            _logger.info("Background service stopped after %d request(s)", self.worked)
        return self.worked

    def install_signal_handlers(self) -> None:
        """Stop on SIGTERM / SIGINT / SIGBREAK (only possible in the main thread)."""
        if threading.current_thread() is not threading.main_thread():
            return
        for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
            number = getattr(signal, name, None)
            if number is not None:
                signal.signal(number, lambda *_: self.stop())


def main(argv: list[str] | None = None) -> None:
    """`vethuq-background [--db FILE] [--once]`: what the installed service runs."""
    parser = argparse.ArgumentParser(prog="vethuq-background", description=__doc__.split("\n")[0])
    parser.add_argument("--db", type=Path, help="The database file to serve (default: the user's).")
    parser.add_argument("--once", action="store_true", help="Work what is waiting, then exit.")
    parser.add_argument("--service", action="store_true", help="Run as the installed service.")
    args = parser.parse_args(argv)
    client = vethuq.VethuQ(db_path=args.db) if args.db else vethuq.VethuQ()
    host = ServiceHost(client)
    host.install_signal_handlers()
    try:
        host.run(once=args.once)
    finally:
        client.close()
