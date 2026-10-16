"""Install now: download the installer the signed policy names, check it, stop the background
service, run the installer silently and bring the service back.

The installer replaces the program that is running this code, so it is started as a separate
process that outlives it. That process runs the installer to the end and then starts the service
again if it was running, which lets queued indexing jobs resume, and then starts the application
again (a silent install does not). Nothing is run unless the file's size and sha256 matched the
signed policy.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from vethuq._updates import InstallerDownload, InstallerError, _Installer
from vethuq_api.indexing import IndexingRefusedError
from vethuq_api.service_probe import SERVICE_NAME, ServiceProbe

SILENT_FLAGS = ("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")


class UpdateInstallRefusedError(IndexingRefusedError):
    """Install now is not possible; the message says why, in words for the person."""


def _launch_detached(command: Sequence[str]) -> None:
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    subprocess.Popen(  # noqa: S603 - built here from a verified file, never from input
        list(command),
        creationflags=flags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


class UpdateInstaller:
    def __init__(
        self,
        probe: ServiceProbe,
        stop_service: Callable[[], None],
        *,
        launch: Callable[[Sequence[str]], None] = _launch_detached,
        fetch: Callable[..., Path] = _Installer.fetch,
        frozen: Callable[[], bool] = lambda: bool(getattr(sys, "frozen", False)),
        application: Callable[[], Path] = lambda: Path(sys.executable),
    ) -> None:
        self._probe = probe
        self._stop_service = stop_service
        self._launch = launch
        self._fetch = fetch
        self._frozen = frozen
        self._application = application

    @staticmethod
    def script(installer: Path, restart_service: bool, application: Path) -> str:
        """The batch file the detached process runs: the installer, then (if the service was
        running) start it, then the application. Starting a service needs administrator rights, so
        it asks the same way stopping did (a UAC prompt). A step that fails does not stop the next,
        so the application always comes back."""

        def quoted(path: Path) -> str:
            return '"' + str(path).replace("%", "%%") + '"'

        lines = ["@echo off", " ".join([quoted(installer), *SILENT_FLAGS])]
        if restart_service:
            lines.append(
                'powershell.exe -NoProfile -Command "Start-Process -FilePath sc.exe '
                f"-ArgumentList 'start','{SERVICE_NAME}' -Verb RunAs -Wait -WindowStyle Hidden\""
            )
        lines.append(f'start "" {quoted(application)}')
        return "\r\n".join(lines) + "\r\n"

    def plan(self, client: Any) -> tuple[Any, InstallerDownload]:
        """The update on offer and its installer. Raises `UpdateInstallRefusedError` when this
        can't be installed from here. Makes no request and changes nothing."""
        if not self._frozen():
            raise UpdateInstallRefusedError(
                "This VethuQ was installed with pip. Use `vethuq update` to see the command "
                "that upgrades it.",
                422,
            )
        result = client.updates.status()
        if not result.notify or result.latest is None:
            raise UpdateInstallRefusedError("There is no update to install.", 409)
        entry = _Installer.entry(client.policy.current().policy, result.distribution)
        if entry is None:
            raise UpdateInstallRefusedError(
                "The signed policy has no installer for this computer. "
                "Download it from the release notes page.",
                422,
            )
        return result, entry

    def install(self, client: Any) -> dict[str, object]:
        """Do the whole thing. Nothing is stopped or run unless the download matched the policy,
        so a refusal never leaves things half done."""
        result, entry = self.plan(client)
        folder = Path(tempfile.mkdtemp(prefix="vethuq-update-"))
        try:
            installer = self._fetch(entry, folder)
        except InstallerError as failure:
            shutil.rmtree(folder, ignore_errors=True)
            raise UpdateInstallRefusedError(str(failure), 502) from failure
        info = self._probe.query()
        was_running = info is not None and info.state in ("RUNNING", "START_PENDING")
        if info is not None:
            try:
                self._stop_service()
            except Exception as failure:  # noqa: BLE001 - nothing has been replaced yet
                shutil.rmtree(folder, ignore_errors=True)
                raise UpdateInstallRefusedError(
                    f"The background service could not be stopped: {failure}", 422
                ) from failure
        script = folder / "update.cmd"
        script.write_text(self.script(installer, was_running, self._application()), "utf-8")
        self._launch(["cmd.exe", "/c", str(script)])
        return {
            "installing": True,
            "version": result.latest,
            "restarts_service": was_running,
        }
