import subprocess

import pytest
from vethuq_core.background import BackgroundService, BackgroundServiceError, ServiceState
from vethuq_core.background import service as service_module


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _sc_output(code, name):
    return (
        "SERVICE_NAME: VethuQBackground\n"
        "        TYPE               : 10  WIN32_OWN_PROCESS\n"
        f"        STATE              : {code}  {name}\n"
    )


class TestWindows:
    @pytest.fixture(autouse=True)
    def _windows(self, monkeypatch):
        monkeypatch.setattr(BackgroundService, "backend", staticmethod(lambda: "windows"))
        self.calls = []

    def _fake_sc(self, monkeypatch, replies):
        def sc(*args, check=True):
            self.calls.append(args)
            reply = replies(args)
            if check and reply.returncode != 0:
                raise BackgroundServiceError(f"sc {args[0]} failed")
            return reply

        monkeypatch.setattr(BackgroundService, "_sc", staticmethod(sc))

    @pytest.mark.parametrize(
        ("code", "state"),
        [
            (1, ServiceState.STOPPED),
            (4, ServiceState.RUNNING),
            (7, ServiceState.PAUSED),
            (2, ServiceState.STARTING),
        ],
    )
    def test_status_reads_the_state_number(self, monkeypatch, code, state):
        self._fake_sc(
            monkeypatch,
            lambda args: (
                _Result(0, _sc_output(code, "X"))
                if args[0] == "query"
                else _Result(
                    0,
                    "START_TYPE         : 2   AUTO_START  (DELAYED)\n"
                    "SERVICE_START_NAME : LocalSystem\n",
                )
            ),
        )

        status = BackgroundService.status()

        assert status.installed and status.state == state
        assert status.account == "LocalSystem"
        assert status.running is (state == ServiceState.RUNNING)

    def test_status_when_not_installed(self, monkeypatch):
        self._fake_sc(monkeypatch, lambda args: _Result(1060, "", "does not exist"))

        status = BackgroundService.status()

        assert not status.installed
        assert status.state == ServiceState.NOT_INSTALLED

    def test_install_creates_the_service_pointing_at_this_data_folder(self, monkeypatch, tmp_path):
        self._fake_sc(monkeypatch, lambda args: _Result(0, _sc_output(1, "STOPPED")))
        monkeypatch.setattr(
            BackgroundService,
            "_worker_args",
            staticmethod(lambda *extra: [r"C:\Program Files\VethuQ\vethuq-worker.exe", *extra]),
        )

        BackgroundService.apply_windows("install", tmp_path)

        create = next(c for c in self.calls if c[0] == "create")
        assert create[1] == "VethuQBackground"
        bin_path = create[create.index("binPath=") + 1]
        assert bin_path.startswith('"C:\\Program Files\\VethuQ\\vethuq-worker.exe" --service')
        assert f"--home {tmp_path}" in bin_path or str(tmp_path) in bin_path
        assert create[create.index("start=") + 1] == "delayed-auto"
        assert "obj=" not in create
        assert ("start", "VethuQBackground") in self.calls
        assert any(c[0] == "failure" for c in self.calls)

    def test_install_as_an_account_passes_its_credentials(self, monkeypatch, tmp_path):
        self._fake_sc(monkeypatch, lambda args: _Result(0, _sc_output(1, "STOPPED")))
        monkeypatch.setattr(
            BackgroundService, "_worker_args", staticmethod(lambda *extra: ["w.exe", *extra])
        )

        BackgroundService.apply_windows("install", tmp_path, r"PC\me", "secret")

        create = next(c for c in self.calls if c[0] == "create")
        assert create[create.index("obj=") + 1] == r"PC\me"
        assert create[create.index("password=") + 1] == "secret"

    @pytest.mark.parametrize(
        ("action", "command"),
        [("start", "start"), ("pause", "pause"), ("resume", "continue")],
    )
    def test_simple_actions_map_to_sc_commands(self, monkeypatch, tmp_path, action, command):
        self._fake_sc(monkeypatch, lambda args: _Result(0, _sc_output(1, "STOPPED")))

        BackgroundService.apply_windows(action, tmp_path)

        assert self.calls == [(command, "VethuQBackground")]

    def test_uninstall_stops_then_deletes(self, monkeypatch, tmp_path):
        self._fake_sc(monkeypatch, lambda args: _Result(0, _sc_output(1, "STOPPED")))

        BackgroundService.apply_windows("uninstall", tmp_path)

        names = [c[0] for c in self.calls]
        assert names.index("stop") < names.index("delete")

    def test_not_elevated_actions_go_through_the_uac_prompt(self, monkeypatch, tmp_path):
        elevated = []
        status = service_module.ServiceStatus(
            True, True, ServiceState.RUNNING, "windows", "VethuQBackground"
        )
        monkeypatch.setattr(BackgroundService, "status", staticmethod(lambda: status))
        monkeypatch.setattr(BackgroundService, "_is_admin", staticmethod(lambda: False))
        monkeypatch.setattr(
            BackgroundService,
            "_elevate",
            staticmethod(lambda action, home, account: elevated.append((action, home, account))),
        )

        BackgroundService.perform("stop", home=tmp_path)

        assert elevated == [("stop", tmp_path, None)]


class TestInstallAccount:
    @pytest.fixture(autouse=True)
    def _windows(self, monkeypatch):
        monkeypatch.setattr(BackgroundService, "backend", staticmethod(lambda: "windows"))
        monkeypatch.setattr(
            BackgroundService,
            "status",
            staticmethod(
                lambda: service_module.ServiceStatus(
                    True, False, ServiceState.NOT_INSTALLED, "windows", "x"
                )
            ),
        )
        monkeypatch.setenv("USERDOMAIN", "PC")
        monkeypatch.setenv("USERNAME", "me")
        self.elevated = []
        monkeypatch.setattr(BackgroundService, "_is_admin", staticmethod(lambda: False))
        monkeypatch.setattr(
            BackgroundService,
            "_elevate",
            staticmethod(lambda action, home, account: self.elevated.append((home, account))),
        )

    def test_it_runs_as_the_current_user_by_default(self, tmp_path):
        BackgroundService.perform("install", home=tmp_path)

        assert self.elevated == [(tmp_path, r"PC\me")]

    def test_another_account_can_be_named(self, tmp_path):
        BackgroundService.perform("install", home=tmp_path, account=r"PC\svc")

        assert self.elevated == [(tmp_path, r"PC\svc")]

    def test_system_runs_it_as_localsystem_without_an_account(self, tmp_path):
        BackgroundService.perform("install", home=tmp_path, system=True, account=r"PC\svc")

        assert self.elevated == [(tmp_path, None)]

    def test_the_home_defaults_to_this_users_data_folder(self, monkeypatch):
        from vethuq_core.paths import Paths

        BackgroundService.perform("install")

        assert self.elevated[0][0] == Paths.resolve_data_root()

    def test_an_elevated_caller_without_a_terminal_must_supply_the_password(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.setattr(BackgroundService, "_is_admin", staticmethod(lambda: True))
        monkeypatch.setattr(service_module.sys, "stdin", None)

        with pytest.raises(BackgroundServiceError, match="password"):
            BackgroundService.perform("install", home=tmp_path)

    def test_an_elevated_caller_passes_the_password_to_sc(self, monkeypatch, tmp_path):
        seen = []
        monkeypatch.setattr(BackgroundService, "_is_admin", staticmethod(lambda: True))
        monkeypatch.setattr(
            BackgroundService,
            "apply_windows",
            staticmethod(lambda *args: seen.append(args)),
        )

        BackgroundService.perform("install", home=tmp_path, password="pw")

        assert seen == [("install", tmp_path, r"PC\me", "pw")]


class TestStatusHome:
    def test_the_home_is_read_from_the_service_command_line(self):
        read = BackgroundService._home_from_command
        assert read(r'"C:\App\vethuq-worker.exe" --service --home "C:\Users\me\VethuQ"') == (
            r"C:\Users\me\VethuQ"
        )
        assert read(r"C:\App\w.exe --service --home D:\Data") == r"D:\Data"
        assert read("w.exe --service") is None

    def test_folders_compare_case_insensitively_on_windows(self, monkeypatch):
        monkeypatch.setattr(service_module.os.path, "normcase", lambda p: p.lower(), raising=False)
        assert BackgroundService.same_folder("/Data/VethuQ", "/data/vethuq/")
        assert not BackgroundService.same_folder("/a", "/b")
        assert not BackgroundService.same_folder(None, "/b")


class TestApplicability:
    @pytest.fixture(autouse=True)
    def _backend(self, monkeypatch):
        monkeypatch.setattr(BackgroundService, "backend", staticmethod(lambda: "windows"))

    def _status(self, monkeypatch, state):
        installed = state != ServiceState.NOT_INSTALLED
        monkeypatch.setattr(
            BackgroundService,
            "status",
            staticmethod(
                lambda: service_module.ServiceStatus(True, installed, state, "windows", "x")
            ),
        )

    @pytest.mark.parametrize("action", ["uninstall", "start", "stop", "restart", "pause", "resume"])
    def test_controlling_a_service_that_is_not_installed_says_so(self, monkeypatch, action):
        self._status(monkeypatch, ServiceState.NOT_INSTALLED)

        with pytest.raises(BackgroundServiceError, match="isn't installed"):
            BackgroundService.perform(action)

    def test_installing_twice_is_refused(self, monkeypatch):
        self._status(monkeypatch, ServiceState.RUNNING)

        with pytest.raises(BackgroundServiceError, match="already installed"):
            BackgroundService.perform("install")

    def test_resume_needs_a_paused_service(self, monkeypatch):
        self._status(monkeypatch, ServiceState.RUNNING)

        with pytest.raises(BackgroundServiceError, match="isn't paused"):
            BackgroundService.perform("resume")

    def test_pause_needs_a_running_service(self, monkeypatch):
        self._status(monkeypatch, ServiceState.STOPPED)

        with pytest.raises(BackgroundServiceError, match="isn't running"):
            BackgroundService.perform("pause")

    def test_unknown_action(self):
        with pytest.raises(BackgroundServiceError, match="Unknown"):
            BackgroundService.perform("explode")

    def test_unsupported_system(self, monkeypatch):
        monkeypatch.setattr(BackgroundService, "backend", staticmethod(lambda: "none"))

        with pytest.raises(BackgroundServiceError, match="isn't supported"):
            BackgroundService.perform("install")


class TestSystemd:
    @pytest.fixture(autouse=True)
    def _systemd(self, monkeypatch, tmp_path):
        monkeypatch.setattr(BackgroundService, "backend", staticmethod(lambda: "systemd"))
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
        self.calls = []
        self.active = "inactive"

        def run(argv, **kwargs):
            self.calls.append(argv[2:])
            if argv[2] == "is-active":
                return _Result(0, self.active)
            if argv[2] == "is-enabled":
                return _Result(0, "enabled")
            return _Result(0)

        monkeypatch.setattr(subprocess, "run", run)

    def test_install_writes_a_user_unit_for_this_data_folder_and_starts_it(self, tmp_path):
        BackgroundService.perform("install", home=tmp_path / "data")

        unit = BackgroundService._unit_path().read_text(encoding="utf-8")
        assert f"Environment=VETHUQ_HOME={tmp_path / 'data'}" in unit
        assert "--service" in unit
        assert ["enable", "--now", "vethuq-background.service"] in self.calls

    def test_status_reflects_systemd(self, tmp_path):
        BackgroundService.perform("install", home=tmp_path)
        self.active = "active"

        assert BackgroundService.status().state == ServiceState.RUNNING

    def test_pause_and_resume_use_the_control_file(self, tmp_path):
        BackgroundService.perform("install", home=tmp_path)
        self.active = "active"

        BackgroundService.perform("pause", home=tmp_path)
        assert BackgroundService.status().state == ServiceState.PAUSED
        BackgroundService.perform("resume", home=tmp_path)
        assert BackgroundService.status().state == ServiceState.RUNNING

    def test_uninstall_removes_the_unit(self, tmp_path):
        BackgroundService.perform("install", home=tmp_path)

        BackgroundService.perform("uninstall", home=tmp_path)

        assert not BackgroundService._unit_path().exists()
        assert BackgroundService.status().installed is False
