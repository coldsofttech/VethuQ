from __future__ import annotations

import hashlib
import sys
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
    log = SimpleNamespace(stopped=0, launched=[])

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
        launch=log.launched.append,
        fetch=fetch or default_fetch,
        frozen=lambda: frozen,
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


class TestInstall:
    def test_stops_the_service_runs_the_installer_silently_and_restarts_the_service(self):
        installer, log = _installer()

        done = installer.install(_client(_policy([_download()])))

        assert done == {"installing": True, "version": "2.0.0", "restarts_service": True}
        assert log.stopped == 1
        ((command,),) = [(c,) for c in log.launched]
        chain = command[-1]
        assert command[:2] == ["cmd.exe", "/c"]
        assert all(flag in chain for flag in SILENT_FLAGS)
        assert chain.endswith("& sc start VethuQBackground")

    def test_a_stopped_service_is_left_stopped(self):
        installer, log = _installer(info=ServiceInfo("STOPPED"))

        done = installer.install(_client(_policy([_download()])))

        assert done["restarts_service"] is False and "sc start" not in log.launched[0][-1]

    def test_no_service_installed_means_nothing_to_stop_or_start(self):
        installer, log = _installer(info=None)

        installer.install(_client(_policy([_download()])))

        assert log.stopped == 0 and "sc start" not in log.launched[0][-1]

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


def test_the_command_is_for_cmd():
    command = UpdateInstaller.command(Path("C:/t/S.exe"), True)

    assert command[0] == "cmd.exe" and sys.platform  # built the same on every platform
