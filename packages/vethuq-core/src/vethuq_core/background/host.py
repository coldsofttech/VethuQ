"""The background service itself: works through the `index_jobs` queue, one run at a time.

`vethuq-worker.exe --service` (Windows service) and `python -m vethuq_core.index.runner --service`
(systemd) both end up in `ServiceHost.run`. Each job is started with `IndexRunner.start_run`, the
same call a one-off `vethuq index run` makes, so the run reads every setting from the database
exactly as it would anywhere else, and `vethuq index status|pause|resume|stop` keep working on
it. The host adds only the queue and its own pause/stop handling.
"""

from __future__ import annotations

import getpass
import os
import signal
import sys
import threading
from pathlib import Path

from vethuq_core.background.service import BackgroundService, BackgroundServiceError
from vethuq_core.index.jobs import IndexJob, IndexJobs
from vethuq_core.index.runner import AlreadyRunningError, IndexRunner
from vethuq_core.logs import Logs
from vethuq_core.paths import Paths
from vethuq_core.storage import default_db_path


class ServiceHost:
    POLL_SECONDS = 2.0
    RUN_POLL_SECONDS = 1.0

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or default_db_path()
        self._stop = threading.Event()
        self._service_paused = False  # the service manager's pause (Windows)
        self._applied_pause = False  # the pause last passed on to the active run
        self._pid: int | None = None
        self._logger = Logs.get_logger("index")

    # -- control, called from the service manager's thread -----------------------------------

    def stop(self) -> None:
        self._stop.set()

    def pause(self) -> None:
        self._service_paused = True

    def resume(self) -> None:
        self._service_paused = False

    @property
    def paused(self) -> bool:
        return self._service_paused or BackgroundService._paused_by_file()

    # -- the loop -----------------------------------------------------------------------------

    def run(self) -> None:
        Logs.setup("index", self._db_path)
        self._logger.info("Background service started (pid=%d)", os.getpid())
        running, _ = IndexRunner.is_running(self._db_path)
        if not running:
            # Whatever a service that died mid-run left 'running' never finished: run it again
            # (indexing is incremental, so it picks up where it left off).
            revived = IndexJobs.requeue_running(self._db_path)
            if revived:
                self._logger.warning("Re-queued %d job(s) left running by an earlier stop", revived)
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception:  # noqa: BLE001 - the service must outlive one bad iteration
                self._logger.exception("Background service iteration failed")
                self._stop.wait(self.POLL_SECONDS * 5)
        self._logger.info("Background service stopped")

    def _tick(self) -> None:
        if self.paused:
            self._stop.wait(self.POLL_SECONDS)
            return
        running, _ = IndexRunner.is_running(self._db_path)
        if running:  # a one-off run (or another service's) is on; wait for it
            self._stop.wait(self.POLL_SECONDS)
            return
        job = IndexJobs.claim_next(self._db_path)
        if job is None:
            self._stop.wait(self.POLL_SECONDS)
            return
        self._run_job(job)

    def _run_job(self, job: IndexJob) -> None:
        self._logger.info(
            "Job %d: %s target=%s", job.id, job.mode, job.target if job.target else "all"
        )
        try:
            pid = IndexRunner.start_run(
                job.target,
                force=True,
                restart=job.restart,
                db_path=self._db_path,
                languages=job.languages,
                job_id=job.id,
            )
        except AlreadyRunningError:
            IndexJobs.requeue(job.id, self._db_path)
            self._stop.wait(self.POLL_SECONDS)
            return
        except Exception as exc:  # noqa: BLE001 - e.g. the source was removed meanwhile
            self._logger.exception("Job %d could not start", job.id)
            IndexJobs.finish(job.id, "failed", str(exc), self._db_path)
            return

        self._pid = pid
        self._applied_pause = False
        while self._alive(pid) and not self._stop.is_set():
            self._sync_pause()
            self._stop.wait(self.RUN_POLL_SECONDS)
        self._pid = None

        if self._alive(pid):  # the service is stopping: hand the run back, resume next start
            self._logger.info("Stopping job %d for service shutdown; it will run again", job.id)
            try:
                IndexRunner.request_stop(self._db_path)
            except Exception:  # noqa: BLE001
                self._logger.exception("Could not stop the index run cleanly")
            IndexJobs.requeue(job.id, self._db_path)
            return
        self._record_outcome(job)

    def _record_outcome(self, job: IndexJob) -> None:
        """Close the job if its worker did not (it died before it could)."""
        state = IndexRunner.read_state(self._db_path)
        if state is not None and state.status == "completed":
            IndexJobs.finish(job.id, "completed", None, self._db_path)
        elif state is not None and state.status == "stopped":
            # stopped from outside (`vethuq index stop`), so it isn't resumed behind their back
            IndexJobs.finish(job.id, "cancelled", None, self._db_path)
        else:
            error = (state.error if state is not None else None) or "The index run did not finish."
            IndexJobs.finish(job.id, "failed", error, self._db_path)
        IndexJobs.prune(self._db_path)
        self._logger.info("Job %d finished: %s", job.id, state.status if state else "unknown")

    def _sync_pause(self) -> None:
        """Pass a change of the service's own pause state on to the run it started."""
        paused = self.paused
        if paused == self._applied_pause:
            return
        try:
            if paused:
                IndexRunner.request_pause(self._db_path)
            else:
                IndexRunner.request_resume(self._db_path)
        except Exception:  # noqa: BLE001 - the run may have just ended
            self._logger.warning("Could not %s the active run", "pause" if paused else "resume")
        self._applied_pause = paused

    @staticmethod
    def _alive(pid: int) -> bool:
        if hasattr(os, "waitpid"):
            try:
                os.waitpid(pid, os.WNOHANG)  # reap our child so a finished run isn't a zombie
            except ChildProcessError:
                pass
        return IndexRunner._is_pid_running(pid)

    # -- process entry points -------------------------------------------------------------------

    @staticmethod
    def _apply_home(argv: list[str]) -> list[str]:
        """Handle `--home <data root>`: make this process (and its workers) use that folder."""
        rest = list(argv)
        if "--home" in rest:
            i = rest.index("--home")
            os.environ[Paths.ENV_VAR] = rest[i + 1]
            del rest[i : i + 2]
        return rest

    @staticmethod
    def main(argv: list[str]) -> int:
        """`--service`: run as the service (the Windows service manager, or systemd)."""
        ServiceHost._apply_home(argv)
        if sys.platform == "win32":
            return ServiceHost._run_windows_service()
        host = ServiceHost()
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: host.stop())
        host.run()
        return 0

    @staticmethod
    def _run_windows_service() -> int:
        import servicemanager  # pywin32, bundled in the desktop build
        import win32service
        import win32serviceutil

        class Service(win32serviceutil.ServiceFramework):
            _svc_name_ = BackgroundService.WINDOWS_NAME
            _svc_display_name_ = BackgroundService.WINDOWS_DISPLAY_NAME

            def __init__(self, args: list[str]) -> None:
                super().__init__(args)
                self.host = ServiceHost()

            def SvcDoRun(self) -> None:  # noqa: N802 - pywin32 API
                self.host.run()

            def SvcStop(self) -> None:  # noqa: N802
                self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=30000)
                self.host.stop()

            def SvcPause(self) -> None:  # noqa: N802
                self.ReportServiceStatus(win32service.SERVICE_PAUSE_PENDING)
                self.host.pause()
                self.ReportServiceStatus(win32service.SERVICE_PAUSED)

            def SvcContinue(self) -> None:  # noqa: N802
                self.ReportServiceStatus(win32service.SERVICE_CONTINUE_PENDING)
                self.host.resume()
                self.ReportServiceStatus(win32service.SERVICE_RUNNING)

        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(Service)
        servicemanager.StartServiceCtrlDispatcher()
        return 0

    @staticmethod
    def control_main(argv: list[str]) -> int:
        """`--service-control <action> [--home P] [--account A] [--quiet]`: the elevated half of
        `BackgroundService.perform` on Windows, and what the installer runs. Returns the exit
        code. Without `--quiet` a failure waits for Enter so the elevated console window, which
        is the only place the reason is shown, doesn't vanish."""
        rest = ServiceHost._apply_home(argv)
        quiet = "--quiet" in rest
        action = rest[0] if rest else ""
        account = rest[rest.index("--account") + 1] if "--account" in rest else None
        try:
            password = getpass.getpass(f"Password for {account}: ") if account else None
            BackgroundService.apply_windows(action, Paths.resolve_data_root(), account, password)
        except (BackgroundServiceError, OSError) as exc:
            print(f"Error: {exc}")  # noqa: T201 - the elevated console window is the only output
            if not quiet:
                input("Press Enter to close this window.")
            return 1
        return 0
