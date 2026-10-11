from __future__ import annotations

import subprocess

import pytest
from vethuq_background.service import (
    UNIT,
    BackgroundService,
    BackgroundServiceError,
    ServiceState,
)


class FakeRunner:
    def __init__(self, outputs=None):
        self.calls: list[list[str]] = []
        self.outputs = outputs or {}

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        for key, (code, out) in self.outputs.items():
            if key in " ".join(command):
                return subprocess.CompletedProcess(command, code, out, "")
        return subprocess.CompletedProcess(command, 0, "", "")


@pytest.fixture
def linux(tmp_path):
    runner = FakeRunner({"is-active": (0, "active\n")})
    service = BackgroundService(
        tmp_path / "db" / "vethuq.db",
        tmp_path / "run" / "service.control",
        runner=runner,
        platform="linux",
        python="/usr/bin/python3",
        unit_dir=tmp_path / "units",
    )
    return service, runner


class TestSystemd:
    def test_install_writes_the_unit_and_enables_it(self, linux, tmp_path):
        service, runner = linux
        status = service.perform("install")
        unit = (tmp_path / "units" / UNIT).read_text()
        assert "ExecStart=/usr/bin/python3 -m vethuq_background --service --db " in unit
        assert str(tmp_path / "db" / "vethuq.db") in unit and "WantedBy=default.target" in unit
        assert ["systemctl", "--user", "daemon-reload"] in runner.calls
        assert ["systemctl", "--user", "enable", "--now", UNIT] in runner.calls
        assert status.state == ServiceState.RUNNING and status.backend == "systemd"
        assert status.db_path == str(tmp_path / "db" / "vethuq.db")

    def test_a_path_with_a_space_is_quoted(self, tmp_path):
        service = BackgroundService(
            tmp_path / "my db" / "vethuq.db", tmp_path / "c", runner=FakeRunner(),
            platform="linux", python="/usr/bin/python3", unit_dir=tmp_path / "u",
        )  # fmt: skip
        assert f'"{tmp_path / "my db" / "vethuq.db"}"' in service.unit_text()

    def test_not_installed_until_the_unit_exists(self, linux):
        service, _ = linux
        assert service.status().state == ServiceState.NOT_INSTALLED

    def test_start_stop_restart_call_systemctl(self, linux):
        service, runner = linux
        service.perform("install")
        runner.calls.clear()
        service.perform("start")
        service.perform("stop")
        service.perform("restart")
        assert [c[2] for c in runner.calls if c[2] in ("start", "stop", "restart")] == [
            "start",
            "stop",
            "restart",
        ]

    def test_pause_and_resume_use_the_control_file(self, linux):
        service, _ = linux
        service.perform("install")
        assert service.perform("pause").state == ServiceState.PAUSED
        assert service.control_file.read_text() == "pause"
        assert service.perform("resume").state == ServiceState.RUNNING

    def test_inactive_is_stopped(self, tmp_path):
        runner = FakeRunner({"is-active": (3, "inactive\n")})
        service = BackgroundService(
            tmp_path / "d" / "v.db", tmp_path / "c", runner=runner, platform="linux",
            unit_dir=tmp_path / "u",
        )  # fmt: skip
        service._unit_dir.mkdir()
        (tmp_path / "u" / UNIT).write_text("[Service]\nExecStart=x\n")
        assert service.status().state == ServiceState.STOPPED

    def test_uninstall_removes_the_unit_and_the_control_file(self, linux, tmp_path):
        service, _ = linux
        service.perform("install")
        service.perform("uninstall")
        assert not (tmp_path / "units" / UNIT).exists() and not service.control_file.exists()

    def test_a_failing_systemctl_is_an_error(self, tmp_path):
        service = BackgroundService(
            tmp_path / "d" / "v.db", tmp_path / "c", runner=FakeRunner({"enable": (1, "no")}),
            platform="linux", unit_dir=tmp_path / "u",
        )  # fmt: skip
        with pytest.raises(BackgroundServiceError, match="systemctl"):
            service.perform("install")


class TestWindows:
    def service(self, tmp_path, admin=True, outputs=None):
        runner = FakeRunner(outputs)
        return (
            BackgroundService(
                tmp_path / "d" / "v.db",
                tmp_path / "c",
                runner=runner,
                platform="win32",
                python="C:/py/python.exe",
                is_admin=lambda: admin,
            ),  # fmt: skip
            runner,
        )

    def test_install_registers_the_service_for_the_account_and_starts_it(self, tmp_path):
        service, runner = self.service(tmp_path)
        service.perform("install", account="HOST\\me", password="pw")
        install = runner.calls[0]
        assert install[:3] == ["C:/py/python.exe", "-m", "vethuq_background.winservice"]
        assert install[-1] == "install" and "--username" in install and "HOST\\me" in install
        assert "pw" in install and "auto" in install
        assert runner.calls[1][-2:] == ["setdb", str(tmp_path / "d" / "v.db")]
        assert ["sc.exe", "start", "VethuQBackground"] in runner.calls

    def test_system_installs_without_an_account(self, tmp_path):
        service, runner = self.service(tmp_path)
        service.perform("install", system=True)
        assert "--username" not in runner.calls[0]

    def test_controls_use_sc(self, tmp_path):
        service, runner = self.service(tmp_path, outputs={"query": (0, "STATE : 4  RUNNING")})
        for action in ("start", "stop", "pause", "resume", "uninstall"):
            service.perform(action)
        verbs = [c[1] for c in runner.calls if c[0] == "sc.exe" and c[1] != "query"]
        assert verbs == ["start", "stop", "pause", "continue", "stop", "delete"]

    def test_status_is_read_from_sc(self, tmp_path):
        for text, state in (
            ("STATE              : 4  RUNNING", ServiceState.RUNNING),
            ("STATE              : 7  PAUSED", ServiceState.PAUSED),
            ("STATE              : 1  STOPPED", ServiceState.STOPPED),
        ):
            service, _ = self.service(tmp_path, outputs={"query": (0, text)})
            assert service.status().state == state

    def test_a_missing_service_is_not_installed(self, tmp_path):
        service, _ = self.service(tmp_path, outputs={"query": (1060, "FAILED 1060")})
        assert service.status().state == ServiceState.NOT_INSTALLED


def test_another_platform_is_unsupported(tmp_path):
    service = BackgroundService(tmp_path / "d" / "v.db", tmp_path / "c", platform="darwin")
    assert service.status().state == ServiceState.UNSUPPORTED
    with pytest.raises(BackgroundServiceError, match="supports Linux"):
        service.perform("install")


def test_an_unknown_action_is_an_error(linux):
    with pytest.raises(BackgroundServiceError, match="no service action"):
        linux[0].perform("explode")
