"""The Windows service class (pywin32): `python -m vethuq_background.winservice install|setdb|...`.

pywin32 hosts it in `pythonservice.exe`; Start / Stop / Pause / Continue from the service manager
reach `ServiceHost` as `run`, `stop`, `pause` and `resume`. The database it serves is stored as a
custom option of the service by `setdb`.
"""

from __future__ import annotations

import sys
import threading

try:  # pywin32 exists only on Windows (`pip install vethuq-background[windows]`)
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil
except ImportError:  # pragma: no cover - other platforms
    win32serviceutil = None

SERVICE_NAME = "VethuQBackground"


if win32serviceutil is not None:  # pragma: no cover - needs Windows

    class VethuQBackgroundService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = "VethuQ background indexing"
        _svc_description_ = "Works through the VethuQ index queue in the background."

        def __init__(self, args):
            super().__init__(args)
            self._over = win32event.CreateEvent(None, 0, 0, None)
            self._host = None

        def GetAcceptedControls(self):
            return super().GetAcceptedControls() | win32service.SERVICE_ACCEPT_PAUSE_CONTINUE

        def SvcDoRun(self):
            import vethuq
            from vethuq_background.host import ServiceHost

            db = win32serviceutil.GetServiceCustomOption(SERVICE_NAME, "db")
            client = vethuq.VethuQ(db_path=db) if db else vethuq.VethuQ()
            self._host = ServiceHost(client)
            servicemanager.LogInfoMsg("VethuQ background service started")
            runner = threading.Thread(target=self._host.run, name="vethuq-host")
            runner.start()
            win32event.WaitForSingleObject(self._over, win32event.INFINITE)
            runner.join()
            client.close()

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            if self._host is not None:
                self._host.stop()
            win32event.SetEvent(self._over)

        def SvcPause(self):
            self.ReportServiceStatus(win32service.SERVICE_PAUSE_PENDING)
            if self._host is not None:
                self._host.pause()
            self.ReportServiceStatus(win32service.SERVICE_PAUSED)

        def SvcContinue(self):
            self.ReportServiceStatus(win32service.SERVICE_CONTINUE_PENDING)
            if self._host is not None:
                self._host.resume()
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - needs Windows
    if win32serviceutil is None:
        raise SystemExit(
            "The Windows service needs Windows and: pip install vethuq-background[windows]"
        )
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["setdb"] and len(args) == 2:
        win32serviceutil.SetServiceCustomOption(SERVICE_NAME, "db", args[1])
        return
    win32serviceutil.HandleCommandLine(VethuQBackgroundService, argv=[sys.argv[0], *args])


if __name__ == "__main__":  # pragma: no cover
    main()
