"""Install and control the VethuQ background indexing service.

Windows: a Windows service (`VethuQBackground`) that runs `vethuq-worker.exe --service` as a
Windows account chosen at install time (by default the user installing it, whose password is
asked for), managed through `sc.exe`. It is never installed automatically: the installer leaves
it to `vethuq background-service install` or the desktop app. Creating or controlling a service
needs administrator rights, so when the caller isn't elevated the action is re-run by
`vethuq-worker.exe --service-control <action>` through a UAC prompt (see `_elevate`); only
reading the status needs no rights.

Linux: a `systemd --user` unit (`vethuq-background.service`), which needs no root. `pause` and
`resume` have no systemd equivalent, so on Linux they write a control file the service checks
(`Paths.run_dir/service.control`); Windows uses the service manager's own pause and continue.

The service serves one data folder (and so one database): by default the installing user's own
(`%LOCALAPPDATA%\\VethuQ`, or the location saved with `vethuq settings location set`), recorded
at install time as `--home`; the account it runs as needs access to it. Everything - sources,
settings, languages, OCR - is read from that database by the same indexing code a one-off run
uses.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from vethuq_core.hints import Hints
from vethuq_core.paths import Paths
from vethuq_core.storage import default_db_path


class BackgroundServiceError(Exception):
    """A background service action could not be carried out."""


class ServiceState:
    NOT_INSTALLED = "not installed"
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    PAUSING = "pausing"
    PAUSED = "paused"
    RESUMING = "resuming"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


@dataclass
class ServiceStatus:
    supported: bool
    installed: bool
    state: str
    backend: str  # "windows" | "systemd" | "none"
    name: str
    start_type: str | None = None
    account: str | None = None
    home: str | None = None  # the data folder the service works on

    @property
    def running(self) -> bool:
        """The service is up and taking jobs (not stopped, not paused)."""
        return self.state == ServiceState.RUNNING

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BackgroundService:
    """Facade over the platform backends."""

    ACTIONS = ("install", "uninstall", "pause", "resume", "stop", "restart", "status", "start")
    WINDOWS_NAME = "VethuQBackground"
    WINDOWS_DISPLAY_NAME = "VethuQ Background Indexer"
    WINDOWS_DESCRIPTION = (
        "Runs VethuQ indexing in the background so documents are indexed without the VethuQ "
        "app or a terminal being open."
    )
    SYSTEMD_UNIT = "vethuq-background.service"
    WORKER_EXE_NAME = "vethuq-worker.exe"
    CONTROL_FILENAME = "service.control"
    _WAIT_SECONDS = 30.0
    # `sc` exit codes
    _ERR_NOT_INSTALLED = 1060
    _ERR_NOT_ACTIVE = 1062
    _ERR_ALREADY_RUNNING = 1056
    _ERR_LOGON_FAILED = 1069
    _STATE_BY_CODE = {
        1: ServiceState.STOPPED,
        2: ServiceState.STARTING,
        3: ServiceState.STOPPING,
        4: ServiceState.RUNNING,
        5: ServiceState.RESUMING,
        6: ServiceState.PAUSING,
        7: ServiceState.PAUSED,
    }

    # -- public API ---------------------------------------------------------------------

    @staticmethod
    def backend() -> str:
        if sys.platform == "win32":
            return "windows"
        if sys.platform.startswith("linux") and shutil.which("systemctl"):
            return "systemd"
        return "none"

    @staticmethod
    def status() -> ServiceStatus:
        backend = BackgroundService.backend()
        if backend == "windows":
            return BackgroundService._windows_status()
        if backend == "systemd":
            return BackgroundService._systemd_status()
        return ServiceStatus(False, False, ServiceState.UNSUPPORTED, "none", "")

    @staticmethod
    def is_enabled() -> bool:
        """Whether indexing goes through the service (it is installed)."""
        return BackgroundService.status().installed

    @staticmethod
    def control_path(db_path: Path | None = None) -> Path:
        return Paths.run_dir(db_path or default_db_path()) / BackgroundService.CONTROL_FILENAME

    @staticmethod
    def current_account() -> str:
        """The signed-in Windows account as `DOMAIN\\user`, the default to run the service as."""
        user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
        domain = os.environ.get("USERDOMAIN")
        return f"{domain}\\{user}" if domain and user else user

    @staticmethod
    def perform(
        action: str,
        *,
        home: Path | None = None,
        account: str | None = None,
        system: bool = False,
        password: str | None = None,
    ) -> ServiceStatus:
        """Run `action` (one of `ACTIONS`), elevating on Windows when needed. Returns the status
        afterwards. Raises `BackgroundServiceError` with a reason when it can't be done.

        For `install` on Windows the service runs as `account` (default: the current user) with
        its password, which is asked for in the elevated window - never on a command line - or
        taken from `password` when the caller is already elevated; `system=True` runs it as
        LocalSystem instead, which needs no password but can't reach mapped drives or the
        user's own folders. `home` is the data folder it works on (default: this user's).
        """
        if action not in BackgroundService.ACTIONS:
            raise BackgroundServiceError(f"Unknown action {action!r}.")
        backend = BackgroundService.backend()
        if backend == "none":
            raise BackgroundServiceError(
                "The background service isn't supported on this system "
                "(it needs Windows, or Linux with systemd)."
            )
        if action == "status":
            return BackgroundService.status()
        current = BackgroundService.status()
        BackgroundService._check_applicable(action, current)
        home = home or Paths.resolve_data_root()
        if action != "install" or system:
            account = None
        elif backend == "windows" and not account:
            account = BackgroundService.current_account()
        if backend == "windows" and not BackgroundService._is_admin():
            BackgroundService._elevate(action, home, account)
        elif backend == "windows":
            if account and password is None:
                if not sys.stdin or not sys.stdin.isatty():
                    raise BackgroundServiceError(
                        f"The password for {account} is needed to run the service as that account."
                    )
                import getpass

                password = getpass.getpass(f"Password for {account}: ")
            BackgroundService.apply_windows(action, home, account, password)
        else:
            BackgroundService._apply_systemd(action, home)
        return BackgroundService.status()

    # -- applicability --------------------------------------------------------------------

    @staticmethod
    def _check_applicable(action: str, current: ServiceStatus) -> None:
        if action == "install" and current.installed:
            raise BackgroundServiceError("The background service is already installed.")
        if action != "install" and not current.installed:
            raise BackgroundServiceError(
                "The background service isn't installed. "
                f"Install it with '{Hints.command('background-service install')}'."
            )
        if action == "pause" and current.state == ServiceState.PAUSED:
            raise BackgroundServiceError("The background service is already paused.")
        if action == "resume" and current.state != ServiceState.PAUSED:
            raise BackgroundServiceError("The background service isn't paused.")
        if action == "pause" and current.state != ServiceState.RUNNING:
            raise BackgroundServiceError("The background service isn't running.")

    # -- Windows ------------------------------------------------------------------------

    @staticmethod
    def worker_exe() -> Path:
        """The executable the service runs: the worker next to this one in a frozen build."""
        if getattr(sys, "frozen", False):
            worker = Path(sys.executable).with_name(BackgroundService.WORKER_EXE_NAME)
            if not worker.exists():
                raise BackgroundServiceError(f"The worker executable was not found at {worker}.")
            return worker
        return Path(sys.executable)

    @staticmethod
    def _worker_args(*extra: str) -> list[str]:
        """Command line that starts the worker code: the exe itself, or `python -m` unfrozen."""
        exe = BackgroundService.worker_exe()
        if getattr(sys, "frozen", False):
            return [str(exe), *extra]
        return [str(exe), "-m", "vethuq_core.index.runner", *extra]

    @staticmethod
    def _sc(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["sc.exe", *args],
            capture_output=True,
            text=True,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if check and result.returncode != 0:
            detail = (result.stdout or result.stderr or "").strip().splitlines()
            message = f"sc {args[0]} failed (exit {result.returncode}): {' '.join(detail[-2:])}"
            if result.returncode == BackgroundService._ERR_LOGON_FAILED:
                message += (
                    " The account's password is wrong, or the account lacks the 'Log on as a "
                    "service' right (Local Security Policy > Local Policies > User Rights "
                    "Assignment)."
                )
            raise BackgroundServiceError(message)
        return result

    @staticmethod
    def _windows_status() -> ServiceStatus:
        name = BackgroundService.WINDOWS_NAME
        query = BackgroundService._sc("query", name, check=False)
        if query.returncode == BackgroundService._ERR_NOT_INSTALLED:
            return ServiceStatus(True, False, ServiceState.NOT_INSTALLED, "windows", name)
        match = re.search(r"STATE\s*:\s*(\d+)", query.stdout or "")
        if query.returncode != 0 or match is None:
            return ServiceStatus(True, True, ServiceState.UNKNOWN, "windows", name)
        state = BackgroundService._STATE_BY_CODE.get(int(match.group(1)), ServiceState.UNKNOWN)
        config = BackgroundService._sc("qc", name, check=False).stdout or ""
        start = re.search(r"START_TYPE\s*:\s*\d+\s+(.+)", config)
        account = re.search(r"SERVICE_START_NAME\s*:\s*(.+)", config)
        binary = re.search(r"BINARY_PATH_NAME\s*:\s*(.+)", config)
        return ServiceStatus(
            True,
            True,
            state,
            "windows",
            name,
            start.group(1).strip() if start else None,
            account.group(1).strip() if account else None,
            BackgroundService._home_from_command(binary.group(1) if binary else ""),
        )

    @staticmethod
    def _home_from_command(command: str) -> str | None:
        """The `--home` folder in the service's command line."""
        match = re.search(r'--home\s+(?:"([^"]+)"|(\S+))', command)
        return (match.group(1) or match.group(2)) if match else None

    @staticmethod
    def same_folder(a: str | Path | None, b: str | Path | None) -> bool:
        """Whether two folder paths name the same place (case-insensitively on Windows)."""
        if a is None or b is None:
            return False
        return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(
            os.path.normpath(str(b))
        )

    @staticmethod
    def _is_admin() -> bool:
        import ctypes

        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False

    @staticmethod
    def _elevate(action: str, home: Path, account: str | None) -> None:
        """Re-run `action` as administrator (UAC prompt) and wait for it to finish."""
        import ctypes
        from ctypes import wintypes

        args = ["--service-control", action, "--home", str(home)]
        if account:
            args += ["--account", account]
        exe, *prefix = BackgroundService._worker_args()
        params = subprocess.list2cmdline([*prefix, *args])

        class ShellExecuteInfo(ctypes.Structure):
            _fields_ = [  # noqa: RUF012
                ("cbSize", wintypes.DWORD),
                ("fMask", wintypes.ULONG),
                ("hwnd", wintypes.HWND),
                ("lpVerb", wintypes.LPCWSTR),
                ("lpFile", wintypes.LPCWSTR),
                ("lpParameters", wintypes.LPCWSTR),
                ("lpDirectory", wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", wintypes.LPCWSTR),
                ("hkeyClass", wintypes.HKEY),
                ("dwHotKey", wintypes.DWORD),
                ("hIconOrMonitor", wintypes.HANDLE),
                ("hProcess", wintypes.HANDLE),
            ]

        see_mask_nocloseprocess = 0x40
        info = ShellExecuteInfo()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = see_mask_nocloseprocess
        info.lpVerb = "runas"
        info.lpFile = exe
        info.lpParameters = params
        info.nShow = 1
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            raise BackgroundServiceError(
                "Administrator permission is needed to change the background service, "
                "and it wasn't granted."
            )
        kernel32 = ctypes.windll.kernel32
        kernel32.WaitForSingleObject(info.hProcess, 0xFFFFFFFF)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        kernel32.CloseHandle(info.hProcess)
        if code.value != 0:
            raise BackgroundServiceError(
                f"The elevated '{action}' failed (exit {code.value}). "
                "Run it from an administrator terminal to see why."
            )

    @staticmethod
    def apply_windows(
        action: str, home: Path, account: str | None = None, password: str | None = None
    ) -> None:
        """Perform `action` directly; the process must already be elevated."""
        name = BackgroundService.WINDOWS_NAME
        sc = BackgroundService._sc
        if action == "install":
            bin_path = subprocess.list2cmdline(
                [*BackgroundService._worker_args("--service", "--home", str(home))]
            )
            args = [
                "create",
                name,
                f"binPath= {bin_path}",
                "start= delayed-auto",
                f"DisplayName= {BackgroundService.WINDOWS_DISPLAY_NAME}",
            ]
            if account:
                args += [f"obj= {account}"]
                if password is not None:
                    args += [f"password= {password}"]
            # `sc` wants the option name and its value as separate argv entries
            sc(*BackgroundService._split_sc_args(args))
            sc("description", name, BackgroundService.WINDOWS_DESCRIPTION)
            # restart after a crash, after 1 minute; forget the failure count after a day
            sc("failure", name, "reset=", "86400", "actions=", "restart/60000")
            sc("start", name)
        elif action == "uninstall":
            if not BackgroundService._windows_status().installed:
                return  # nothing to remove (the uninstaller runs this either way)
            BackgroundService._stop_windows(name)
            sc("delete", name)
        elif action == "start":
            sc("start", name)
        elif action == "stop":
            BackgroundService._stop_windows(name)
        elif action == "pause":
            sc("pause", name)
        elif action == "resume":
            sc("continue", name)
        elif action == "restart":
            BackgroundService._stop_windows(name)
            sc("start", name)

    @staticmethod
    def _split_sc_args(args: list[str]) -> list[str]:
        """Turn `"binPath= X"` into `"binPath=", "X"`, the form `sc` expects as argv."""
        out: list[str] = []
        for arg in args:
            key, sep, value = arg.partition("= ")
            if sep and re.fullmatch(r"[A-Za-z]+", key):
                out += [f"{key}=", value]
            else:
                out.append(arg)
        return out

    @staticmethod
    def _stop_windows(name: str) -> None:
        result = BackgroundService._sc("stop", name, check=False)
        if result.returncode not in (0, BackgroundService._ERR_NOT_ACTIVE):
            BackgroundService._sc("stop", name)  # raises with the reason
        deadline = time.monotonic() + BackgroundService._WAIT_SECONDS
        while time.monotonic() < deadline:
            if BackgroundService._windows_status().state == ServiceState.STOPPED:
                return
            time.sleep(0.5)
        raise BackgroundServiceError("The background service didn't stop in time.")

    # -- Linux (systemd --user) -----------------------------------------------------------

    @staticmethod
    def _unit_path() -> Path:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        return config / "systemd" / "user" / BackgroundService.SYSTEMD_UNIT

    @staticmethod
    def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["systemctl", "--user", *args], capture_output=True, text=True, check=False
        )
        if check and result.returncode != 0:
            raise BackgroundServiceError(
                f"systemctl {args[0]} failed: {(result.stderr or result.stdout).strip()}"
            )
        return result

    @staticmethod
    def _systemd_status() -> ServiceStatus:
        unit = BackgroundService.SYSTEMD_UNIT
        if not BackgroundService._unit_path().exists():
            return ServiceStatus(True, False, ServiceState.NOT_INSTALLED, "systemd", unit)
        active = BackgroundService._systemctl("is-active", unit, check=False).stdout.strip()
        state = {
            "active": ServiceState.RUNNING,
            "activating": ServiceState.STARTING,
            "deactivating": ServiceState.STOPPING,
            "inactive": ServiceState.STOPPED,
            "failed": ServiceState.STOPPED,
        }.get(active, ServiceState.UNKNOWN)
        if state == ServiceState.RUNNING and BackgroundService._paused_by_file():
            state = ServiceState.PAUSED
        enabled = BackgroundService._systemctl("is-enabled", unit, check=False).stdout.strip()
        try:
            text = BackgroundService._unit_path().read_text(encoding="utf-8")
        except OSError:
            text = ""
        home = re.search(r"^Environment=VETHUQ_HOME=(.+)$", text, re.MULTILINE)
        return ServiceStatus(
            True,
            True,
            state,
            "systemd",
            unit,
            "enabled" if enabled == "enabled" else "manual",
            None,
            home.group(1).strip() if home else None,
        )

    @staticmethod
    def _paused_by_file() -> bool:
        try:
            return BackgroundService.control_path().read_text(encoding="utf-8").strip() == "pause"
        except OSError:
            return False

    @staticmethod
    def _apply_systemd(action: str, home: Path) -> None:
        unit = BackgroundService.SYSTEMD_UNIT
        ctl = BackgroundService._systemctl
        if action == "install":
            exec_start = subprocess.list2cmdline(
                [sys.executable, "-m", "vethuq_core.index.runner", "--service"]
            )
            path = BackgroundService._unit_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "[Unit]\n"
                "Description=VethuQ background indexer\n\n"
                "[Service]\n"
                f"Environment=VETHUQ_HOME={home}\n"
                f"ExecStart={exec_start}\n"
                "Restart=on-failure\n"
                "RestartSec=60\n\n"
                "[Install]\n"
                "WantedBy=default.target\n",
                encoding="utf-8",
            )
            ctl("daemon-reload")
            ctl("enable", "--now", unit)
        elif action == "uninstall":
            ctl("disable", "--now", unit, check=False)
            BackgroundService._unit_path().unlink(missing_ok=True)
            ctl("daemon-reload")
        elif action in ("start", "stop", "restart"):
            ctl(action, unit)
        elif action == "pause":
            BackgroundService.control_path().write_text("pause", encoding="utf-8")
        elif action == "resume":
            BackgroundService.control_path().unlink(missing_ok=True)
