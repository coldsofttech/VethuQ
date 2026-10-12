"""Indexing for the interface: start a run (through the background service when it is running,
otherwise in this process), follow it, control it, and look back at what happened."""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Callable
from typing import Any

from vethuq_api.service_probe import SERVICE_NAME, ServiceProbe, WindowsServiceProbe, colour

MODES = ("run", "restart", "reindex", "file")
_NEEDS_TARGET = ("reindex", "file")


class IndexingRefusedError(Exception):
    """The run cannot start (the message says why); `status` is the HTTP status to answer with."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.status = status


class IndexingService:
    """What the Sources and Indexing screens need from the core's `index`."""

    def __init__(self, client: Callable[[], Any], probe: ServiceProbe | None = None) -> None:
        self._client = client
        self._probe = probe or WindowsServiceProbe()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._one_off: dict[str, Any] | None = None
        self._error: str | None = None

    # ----- state ------------------------------------------------------------------------------

    def one_off_active(self) -> bool:
        """A run this process started is going (it stops if the application closes)."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def state(self) -> dict[str, object]:
        """Everything the status bar and the Indexing page show, in one answer."""
        client = self._client()
        status = client.index.status()
        service_running = client.index.queue.service_running()
        active = bool(status and status.active)
        one_off = self.one_off_active()
        if one_off:
            mode = "one-off"
        elif active:
            mode = "service" if service_running else "external"
        else:
            mode = "idle"
        payload: dict[str, object] = {
            "run": status.run.to_dict() if status else None,
            "active": active,
            "paused": bool(status and status.paused),
            "stopping": bool(status and status.stopping),
            "finished": status.finished if status else True,
            "stalled": bool(status and status.stalled),
            "control": status.control if status else "run",
            "eta": status.eta.to_dict() if status else None,
            "current_files": list(status.current_files) if status else [],
            "workers_active": status.workers_active if status else 0,
            "remote_jobs_open": status.remote_jobs_open if status else 0,
            "queued": client.index.queue.queued(),
            "runner": {
                "mode": mode,
                "service_running": service_running,
                "one_off": self._one_off if one_off else None,
            },
            "error": self._error,
            "service": self._service(active, service_running),
        }
        return payload

    def _service(self, working: bool, announced: bool) -> dict[str, object] | None:
        info = self._probe.query()
        if info is None:
            return None  # not installed: the interface shows nothing about it
        dot, label, tooltip = colour(info, working=working, announced=announced)
        return {
            "installed": True,
            "state": info.state,
            "colour": dot,
            "label": label,
            "tooltip": tooltip,
        }

    def refresh(self) -> dict[str, object]:
        """Take in the results of remote jobs that have finished, then the state. A failure to ask
        a remote tier is not a failure to show the state."""
        client = self._client()
        status = client.index.status()
        if status is not None and status.remote_jobs_open:
            try:
                client.index.collect()
            except Exception as error:  # noqa: BLE001 - shown in the state, not raised
                self._error = f"Collecting remote results failed: {error}"
        return self.state()

    # ----- start and control ------------------------------------------------------------------

    def start(self, mode: str, target: int | str | None = None) -> dict[str, object]:
        """Start a run. With the background service running the request goes to its queue,
        otherwise it runs on a thread here."""
        if mode not in MODES:
            raise IndexingRefusedError(f"mode is one of {', '.join(MODES)}.", 422)
        if mode in _NEEDS_TARGET and target is None:
            raise IndexingRefusedError(f"{mode} needs a source or a file.", 422)
        client = self._client()
        status = client.index.status()
        if self.one_off_active() or (status is not None and status.active):
            raise IndexingRefusedError("A run is already going. Stop it, or wait for it to end.")
        self._enough_credits(client, mode, target)
        self._error = None
        if client.index.queue.service_running():
            client.index.queue.submit(target, mode=mode)
            return self.state()
        self._begin(client, mode, target)
        return self.state()

    @staticmethod
    def _enough_credits(client: Any, mode: str, target: int | str | None) -> None:
        """Block a run whose OCR the wallet cannot pay for."""
        if mode == "file":
            return  # the estimate is for sources; a single file is cheap and the run says if not
        estimate = client.credits.estimate(target)
        if estimate.ocr_pages and not estimate.affordable:
            raise IndexingRefusedError(
                f"Not enough credits: this run needs up to {estimate.maximum:g} and the wallet "
                "cannot cover it. Credits reset at 00:00 UTC.",
                402,
            )

    def _begin(self, client: Any, mode: str, target: int | str | None) -> None:
        calls = {
            "run": client.index.run,
            "restart": client.index.restart,
            "reindex": client.index.reindex,
            "file": client.index.reindex_file,
        }
        call = calls[mode]

        def work() -> None:
            try:
                call(target)
            except Exception as error:  # noqa: BLE001 - kept to show; the thread must not die loudly
                self._error = str(error)

        with self._lock:
            self._one_off = {"mode": mode, "target": target}
            self._thread = threading.Thread(target=work, name="vethuq-index", daemon=True)
            self._thread.start()

    def pause(self) -> dict[str, object]:
        self._client().index.pause()
        return self.state()

    def resume(self) -> dict[str, object]:
        self._client().index.resume()
        return self.state()

    def stop(self, *, wait: bool = False) -> dict[str, object]:
        """Stop the run that is going (it ends after the file it is on); or, when a request is
        still waiting in the service's queue, take that out."""
        client = self._client()
        status = client.index.status()
        if status is not None and status.active:
            client.index.stop(wait=wait, timeout=0.25 if wait else None)
        else:
            for job in client.index.queue.list("queued"):
                client.index.queue.cancel(job.id)
        return self.state()

    def stop_for_close(self) -> None:
        """The application is closing during a run of its own: stop it and wait for the end."""
        if self.one_off_active():
            try:
                self._client().index.stop(wait=True, timeout=0.25)
            except Exception:  # noqa: BLE001 - closing must go on
                return
            thread = self._thread
            if thread is not None:
                thread.join(timeout=15)

    # ----- looking back -----------------------------------------------------------------------

    def history(
        self,
        *,
        status: str | None = None,
        target: int | str | None = None,
        sort: str = "started_at",
        order: str = "desc",
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        runs = self._client().index.history(
            target=target,
            status=status or None,
            sort_by=sort,
            order=order,
            limit=limit,
            offset=offset,
        )
        return [run.to_dict() for run in runs]

    def jobs(self, limit: int = 50) -> list[dict[str, object]]:
        return [job.to_dict() for job in self._client().index.jobs(limit=limit)]

    def requests(self, limit: int = 50) -> list[dict[str, object]]:
        return [job.to_dict() for job in self._client().index.queue.list(None, limit)]

    def cancel_request(self, job_id: int) -> dict[str, object]:
        return self._client().index.queue.cancel(job_id).to_dict()

    # ----- the service ------------------------------------------------------------------------

    def service_action(self, action: str) -> dict[str, object]:
        """Start, stop, pause or resume the Windows service (Windows asks for administrator
        approval). Uses the background package when it is installed, else `sc.exe` elevated."""
        if action not in ("start", "stop", "pause", "resume"):
            raise IndexingRefusedError("Start, stop, pause or resume the service.", 422)
        if self._probe.query() is None:
            raise IndexingRefusedError("The background service is not installed.", 404)
        try:
            from vethuq_background.service import BackgroundService

            client = self._client()
            BackgroundService(client.db_path, client.index.queue.control_file()).perform(action)
        except ImportError:
            self._elevated_sc(action)
        except Exception as error:  # noqa: BLE001
            message = f"The service could not be told to {action}: {error}"
            raise IndexingRefusedError(message, 422) from error
        forget = getattr(self._probe, "forget", None)
        if callable(forget):
            forget()
        return self.state()

    @staticmethod
    def _elevated_sc(action: str) -> None:
        verb = {"start": "start", "stop": "stop", "pause": "pause", "resume": "continue"}[action]
        if sys.platform != "win32":
            raise IndexingRefusedError("Service control is available on Windows.", 422)
        command = (
            f"Start-Process -FilePath sc.exe -ArgumentList '{verb}','{SERVICE_NAME}' "
            "-Verb RunAs -Wait -WindowStyle Hidden"
        )
        done = subprocess.run(  # noqa: S603
            ["powershell.exe", "-NoProfile", "-Command", command],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if done.returncode:
            raise IndexingRefusedError(
                done.stderr.strip() or "The administrator approval was declined.", 422
            )
