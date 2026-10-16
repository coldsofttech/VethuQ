from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from vethuq._policy import Policy
from vethuq._updates import InstallerError
from vethuq_api.indexing import IndexingRefusedError
from vethuq_api.maintenance_service import MaintenanceService
from vethuq_api.service_probe import ServiceInfo
from vethuq_api.update_install import SILENT_FLAGS, UpdateInstaller

BYTES = b"setup"
DIGEST = hashlib.sha256(BYTES).hexdigest()


def _policy(downloads):
    return Policy.from_payload(
        {
            "schema_version": 1,
            "sequence": 1,
            "issued_at": "2026-10-01T12:00:00Z",
            "kid": "k",
            "versions": {
                "desktop": {"latest": "2.0.0", "minimum_supported": "1.0.0", "downloads": downloads}
            },
        }
    )


def _download(**over):
    platform = "windows-x64"
    entry = {
        "platform": platform,
        "url": "https://dl.test/S.exe",
        "size": len(BYTES),
        "sha256": DIGEST,
    }
    return {**entry, **over}


def _client(policy, notify=True, latest="2.0.0"):
    result = SimpleNamespace(notify=notify, latest=latest, distribution="desktop")
    return SimpleNamespace(
        updates=SimpleNamespace(status=lambda: result),
        policy=SimpleNamespace(current=lambda: SimpleNamespace(policy=policy)),
    )


class _Probe:
    def __init__(self, info):
        self.info = info

    def query(self):
        return self.info


@pytest.fixture(autouse=True)
def _windows_platform(monkeypatch):
    monkeypatch.setattr(
        "vethuq._updates.installer._Installer.platform_key", staticmethod(lambda: "windows-x64")
    )


RUNNING = ServiceInfo("RUNNING")


def _installer(info=RUNNING, frozen=True, fetch=None, stop=None):
    log = SimpleNamespace(stopped=0, launched=[], scripts=[])

    def launch(command):
        log.launched.append(command)
        log.scripts.append(Path(command[-1]).read_text("utf-8"))

    def default_fetch(entry, folder):
        path = Path(folder) / "S.exe"
        path.write_bytes(BYTES)
        return path

    def do_stop():
        log.stopped += 1
        if stop:
            raise stop

    installer = UpdateInstaller(
        _Probe(info),
        do_stop,
        launch=launch,
        fetch=fetch or default_fetch,
        frozen=lambda: frozen,
        application=lambda: Path("C:/Apps/VethuQ/vethuqd.exe"),
    )
    return installer, log


class TestPlan:
    def test_a_pip_install_is_pointed_to_the_command(self):
        installer, _ = _installer(frozen=False)

        with pytest.raises(IndexingRefusedError, match="vethuq update"):
            installer.plan(_client(_policy([_download()])))

    def test_no_update_means_nothing_to_install(self):
        installer, _ = _installer()

        with pytest.raises(IndexingRefusedError, match="no update"):
            installer.plan(_client(_policy([_download()]), notify=False))

    def test_a_policy_without_an_installer_for_this_computer_is_refused(self):
        installer, _ = _installer()

        with pytest.raises(IndexingRefusedError, match="no installer"):
            installer.plan(_client(_policy([_download(platform="linux-x64")])))


def _script(log) -> str:
    """The batch file the launched command runs (read while the temp folder still exists)."""
    (command,) = log.launched
    assert command[:2] == ["cmd.exe", "/c"]
    return log.scripts[0]


class TestInstall:
    def test_stops_the_service_runs_the_installer_silently_restarts_the_service_and_the_app(self):
        installer, log = _installer()

        done = installer.install(_client(_policy([_download()])))

        assert done == {"installing": True, "version": "2.0.0", "restarts_service": True}
        assert log.stopped == 1
        lines = _script(log).splitlines()
        assert lines[0] == "@echo off"
        assert lines[1].endswith(" ".join(SILENT_FLAGS)) and "S.exe" in lines[1]
        assert "sc.exe" in lines[2] and "VethuQBackground" in lines[2] and "-Verb RunAs" in lines[2]
        assert lines[3].startswith('start "" "') and lines[3].endswith('vethuqd.exe"')

    def test_the_service_is_started_before_the_app_and_after_the_installer(self):
        installer, log = _installer()
        installer.install(_client(_policy([_download()])))
        text = _script(log)

        assert text.index("S.exe") < text.index("sc.exe") < text.index("vethuqd.exe")

    def test_a_stopped_service_is_left_stopped_but_the_app_still_comes_back(self):
        installer, log = _installer(info=ServiceInfo("STOPPED"))

        done = installer.install(_client(_policy([_download()])))

        text = _script(log)
        assert done["restarts_service"] is False and "sc.exe" not in text
        assert "vethuqd.exe" in text

    def test_no_service_installed_means_nothing_to_stop_or_start(self):
        installer, log = _installer(info=None)

        installer.install(_client(_policy([_download()])))

        assert log.stopped == 0 and "sc.exe" not in _script(log)

    def test_a_download_that_fails_verification_stops_nothing_and_runs_nothing(self):
        def bad(entry, folder):
            raise InstallerError("The installer does not match its checksum; it was not run.")

        installer, log = _installer(fetch=bad)

        with pytest.raises(IndexingRefusedError, match="checksum"):
            installer.install(_client(_policy([_download()])))

        assert log.stopped == 0 and log.launched == []

    def test_a_service_that_will_not_stop_means_the_installer_is_not_run(self):
        installer, log = _installer(stop=RuntimeError("access denied"))

        with pytest.raises(IndexingRefusedError, match="access denied"):
            installer.install(_client(_policy([_download()])))

        assert log.launched == []


class TestScript:
    def test_percent_signs_in_paths_are_escaped_for_cmd(self):
        text = UpdateInstaller.script(Path("C:/100%/S.exe"), False, Path("C:/a/app.exe"))

        assert "100%%" in text and "100%/" not in text

    def test_lines_end_the_windows_way(self):
        assert UpdateInstaller.script(Path("S.exe"), True, Path("a.exe")).endswith("\r\n")


class TestThroughTheMaintenanceService:
    def test_a_refusal_is_immediate_and_starts_no_task(self):
        installer, _ = _installer(frozen=False)
        service = MaintenanceService(lambda: _client(_policy([_download()])), installer)

        with pytest.raises(IndexingRefusedError):
            service.update_install()

        assert service.tasks()["update-install"]["running"] is False

    def test_without_an_installer_it_is_not_available(self):
        with pytest.raises(IndexingRefusedError, match="not available"):
            MaintenanceService(lambda: None).update_install()
