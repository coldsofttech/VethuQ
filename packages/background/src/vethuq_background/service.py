"""Install and control the background service.

Linux: a `systemd --user` unit (`vethuq-background.service`), which needs no root. systemd has no
pause, so `pause` and `resume` write the control file the host watches.

Windows: a Windows service (`VethuQBackground`, `winservice.py`, built on pywin32) that starts with
the computer and runs as a Windows account chosen at install time (the installing user by default,
whose password is asked for). Creating or controlling a service needs administrator rights, so when
the caller is not elevated the action is run again through a UAC prompt.

The service serves one data folder (one database): recorded at install time. It is never installed
automatically.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

UNIT = "vethuq-background.service"
WINDOWS_NAME = "VethuQBackground"


class BackgroundServiceError(Exception):
    """The service could not be installed or controlled."""


class ServiceState:
    NOT_INSTALLED = "not_installed"
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class ServiceStatus:
    state: str
    backend: str  # systemd, windows or unsupported
    detail: str = ""
    db_path: str | None = None  # the database it serves

    @property
    def running(self) -> bool:
        return self.state in (ServiceState.RUNNING, ServiceState.PAUSED)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"running": self.running}


Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _run(command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - the commands are built here, never from input
        list(command), capture_output=True, text=True, check=False, **kwargs
    )


class BackgroundService:
    """The service for the data folder of `db_path`. `runner`, `platform` and `python` can be
    replaced (tests do)."""

    def __init__(
        self,
        db_path: Path,
        control_file: Path,
        *,
        runner: Runner = _run,
        platform: str | None = None,
        python: str | None = None,
        unit_dir: Path | None = None,
        is_admin: Callable[[], bool] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.control_file = Path(control_file)
        self._run = runner
        self._platform = platform or sys.platform
        self._python = python or sys.executable
        self._unit_dir = unit_dir or Path.home() / ".config" / "systemd" / "user"
        self._is_admin = is_admin or self._windows_admin

    # ----- which backend ----------------------------------------------------------------------

    def backend(self) -> str:
        if self._platform.startswith("linux"):
            return "systemd"
        if self._platform == "win32":
            return "windows"
        return "unsupported"

    def _require(self) -> str:
        backend = self.backend()
        if backend == "unsupported":
            raise BackgroundServiceError(
                f"The background service supports Linux (systemd) and Windows, not {self._platform}"
            )
        return backend

    def command_line(self) -> list[str]:
        """What the service runs."""
        return [self._python, "-m", "vethuq_background", "--service", "--db", str(self.db_path)]

    # ----- the actions ------------------------------------------------------------------------

    def perform(self, action: str, **options: Any) -> ServiceStatus:
        """Do `action` (install, uninstall, start, stop, restart, pause, resume) and return the
        status after it. Raises `BackgroundServiceError`."""
        backend = self._require()
        if action not in ("install", "uninstall", "start", "stop", "restart", "pause", "resume"):
            raise BackgroundServiceError(f"There is no service action {action!r}.")
        getattr(self, f"_{backend}_{action}")(**options)
        return self.status()

    def status(self) -> ServiceStatus:
        backend = self.backend()
        if backend == "systemd":
            return self._systemd_status()
        if backend == "windows":
            return self._windows_status()
        return ServiceStatus(
            ServiceState.UNSUPPORTED, backend, f"{self._platform} is not supported"
        )

    # ----- systemd ----------------------------------------------------------------------------

    def unit_text(self) -> str:
        exec_start = " ".join(f'"{part}"' if " " in part else part for part in self.command_line())
        return (
            "[Unit]\nDescription=VethuQ background indexing\nAfter=default.target\n\n"
            f"[Service]\nType=simple\nExecStart={exec_start}\nRestart=on-failure\nRestartSec=5\n\n"
            "[Install]\nWantedBy=default.target\n"
        )

    def _systemctl(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = self._run(["systemctl", "--user", *args])
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise BackgroundServiceError(f"systemctl {' '.join(args)} failed: {detail}")
        return result

    def _unit_path(self) -> Path:
        return self._unit_dir / UNIT

    def _systemd_install(self, **_: Any) -> None:
        self._unit_dir.mkdir(parents=True, exist_ok=True)
        self._unit_path().write_text(self.unit_text(), encoding="utf-8")
        self._write_control("run")
        self._systemctl("daemon-reload")
        self._systemctl("enable", "--now", UNIT)

    def _systemd_uninstall(self) -> None:
        self._systemctl("disable", "--now", UNIT, check=False)
        self._unit_path().unlink(missing_ok=True)
        self._systemctl("daemon-reload", check=False)
        self.control_file.unlink(missing_ok=True)

    def _systemd_start(self) -> None:
        self._write_control("run")
        self._systemctl("start", UNIT)

    def _systemd_stop(self) -> None:
        self._systemctl("stop", UNIT)

    def _systemd_restart(self) -> None:
        self._write_control("run")
        self._systemctl("restart", UNIT)

    def _systemd_pause(self) -> None:
        self._write_control("pause")

    def _systemd_resume(self) -> None:
        self._write_control("run")

    def _systemd_status(self) -> ServiceStatus:
        if not self._unit_path().exists():
            return ServiceStatus(ServiceState.NOT_INSTALLED, "systemd")
        active = self._systemctl("is-active", UNIT, check=False).stdout.strip()
        if active == "active":
            paused = self._control() == "pause"
            state = ServiceState.PAUSED if paused else ServiceState.RUNNING
        else:
            state = ServiceState.STOPPED
        return ServiceStatus(state, "systemd", active, self._served_db())

    def _served_db(self) -> str | None:
        try:
            for line in self._unit_path().read_text(encoding="utf-8").splitlines():
                if line.startswith("ExecStart="):
                    parts = line.removeprefix("ExecStart=").replace('"', "").split()
                    return parts[parts.index("--db") + 1] if "--db" in parts else None
        except OSError:
            return None
        return None

    # ----- control file -----------------------------------------------------------------------

    def _write_control(self, word: str) -> None:
        self.control_file.parent.mkdir(parents=True, exist_ok=True)
        self.control_file.write_text(word, encoding="utf-8")

    def _control(self) -> str:
        try:
            return self.control_file.read_text(encoding="utf-8").strip()
        except OSError:
            return "run"

    # ----- Windows ----------------------------------------------------------------------------

    @staticmethod
    def _windows_admin() -> bool:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False

    def _sc(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """`sc.exe`, elevated through UAC when the caller is not an administrator."""
        if not self._is_admin():
            return self._elevated(["sc.exe", *args], check)
        result = self._run(["sc.exe", *args])
        if check and result.returncode != 0:
            raise BackgroundServiceError(
                f"sc.exe {' '.join(args)} failed: {(result.stdout or result.stderr).strip()}"
            )
        return result

    def _elevated(self, command: Sequence[str], check: bool) -> subprocess.CompletedProcess[str]:
        """Run `command` with administrator rights (a UAC prompt) and wait for it."""
        if not self._platform == "win32":
            raise BackgroundServiceError("Administrator rights are needed.")
        import ctypes

        shell = ctypes.windll.shell32  # type: ignore[attr-defined]
        arguments = subprocess.list2cmdline(list(command[1:]))
        code = shell.ShellExecuteW(None, "runas", command[0], arguments, None, 0)
        if code <= 32:
            raise BackgroundServiceError("Administrator permission was not given.")
        return subprocess.CompletedProcess(list(command), 0, "", "")

    def _windows_install(
        self,
        account: str | None = None,
        password: str | None = None,
        system: bool = False,
        **_: Any,
    ) -> None:
        command = [self._python, "-m", "vethuq_background.winservice", "--startup", "auto"]
        if not system:
            account = account or os.environ.get("USERDOMAIN", ".") + "\\" + os.environ.get(
                "USERNAME", ""
            )
            command += ["--username", account]
            if password:
                command += ["--password", password]
        command += ["install"]
        self._write_control("run")
        self._run_admin(command)
        self._run_admin(
            [self._python, "-m", "vethuq_background.winservice", "setdb", str(self.db_path)]
        )
        self._sc("start", WINDOWS_NAME)

    def _run_admin(self, command: Sequence[str]) -> None:
        if self._is_admin():
            result = self._run(list(command))
            if result.returncode != 0:
                raise BackgroundServiceError(
                    f"{' '.join(command[:3])} failed: {(result.stdout or result.stderr).strip()}"
                )
        else:
            self._elevated(command, True)

    def _windows_uninstall(self) -> None:
        self._sc("stop", WINDOWS_NAME, check=False)
        self._sc("delete", WINDOWS_NAME)
        self.control_file.unlink(missing_ok=True)

    def _windows_start(self) -> None:
        self._write_control("run")
        self._sc("start", WINDOWS_NAME)

    def _windows_stop(self) -> None:
        self._sc("stop", WINDOWS_NAME)

    def _windows_restart(self) -> None:
        self._sc("stop", WINDOWS_NAME, check=False)
        self._sc("start", WINDOWS_NAME)

    def _windows_pause(self) -> None:
        self._sc("pause", WINDOWS_NAME)

    def _windows_resume(self) -> None:
        self._sc("continue", WINDOWS_NAME)

    def _windows_status(self) -> ServiceStatus:
        result = self._run(["sc.exe", "query", WINDOWS_NAME])
        text = result.stdout or ""
        if result.returncode == 1060 or "1060" in text:
            return ServiceStatus(ServiceState.NOT_INSTALLED, "windows")
        states = {"RUNNING": ServiceState.RUNNING, "PAUSED": ServiceState.PAUSED}
        state = ServiceState.STOPPED
        for word, mapped in states.items():
            if f" {word}" in text:
                state = mapped
        return ServiceStatus(state, "windows", text.strip().splitlines()[-1] if text else "")
