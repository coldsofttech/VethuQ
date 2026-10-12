"""The CLI installer files, and the parts of scripts/release/release.py that need no build."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "packages" / "cli" / "installer"
SHARED = ROOT / "installer" / "shared"
DEFAULT_ADDONS = {
    "english",
    "pdf",
    "txt",
    "csv",
    "markdown",
    "paddle",
    "ocr-quick",
    "like",
    "exact",
    "full-text",
    "case",
    "unicode",
}
NOT_DEFAULT = {"lexical", "proximity", "fuzzy", "noise-fuzzy", "leetspeak"}


def load(name: str):
    path = ROOT / "scripts" / "release" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"release_{name}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


release = load("release")
plan = load("plan")


class TestInstallerFiles:
    @pytest.mark.parametrize("name", ["vethuq-cli.iss", "vethuq_entry.py"])
    def test_the_file_exists(self, name):
        assert (INSTALLER / name).is_file()

    @pytest.mark.parametrize(
        "name",
        ["addons_hook.py", "LICENSE.rtf", "vethuq.ico", "wizard_large.bmp", "wizard_small.bmp"],
    )
    def test_what_both_installers_use_is_shared_not_in_either_package(self, name):
        assert (SHARED / name).is_file()
        assert not (INSTALLER / name).exists()
        assert not (IC_INSTALLER / name).exists()

    def test_the_shells_entry_script_is_with_the_shell(self):
        assert (IC_INSTALLER / "vethuqic_entry.py").is_file()
        assert not (INSTALLER / "vethuqic_entry.py").exists()

    def test_the_wizard_images_have_inno_sizes(self):
        assert Image.open(SHARED / "wizard_large.bmp").size == (164, 314)
        assert Image.open(SHARED / "wizard_small.bmp").size == (55, 55)

    def test_the_inno_script_uses_the_images_and_is_command_line_only(self):
        script = (INSTALLER / "vethuq-cli.iss").read_text(encoding="utf-8")
        for line in (
            "SetupIconFile=..\\..\\..\\installer\\shared\\vethuq.ico",
            "WizardImageFile=..\\..\\..\\installer\\shared\\wizard_large.bmp",
            "WizardSmallImageFile=..\\..\\..\\installer\\shared\\wizard_small.bmp",
            "LicenseFile=..\\..\\..\\installer\\shared\\LICENSE.rtf",
        ):
            assert line in script
        assert re.search(r"^Source: .*build\\cli\\vethuq\\lib\\", script, re.M)
        assert re.search(r"^Source: .*build\\cli\\vethuq\\add-ons\\", script, re.M)
        code = "\n".join(line for line in script.splitlines() if not line.startswith(";"))
        for word in ("VethuQ-UI", "worker", "[Icons]", "desktopicon", "interactive"):
            assert word not in code

    def test_the_spec_bakes_in_exactly_the_default_add_ons(self):
        spec = (SHARED / "vethuq.spec").read_text(encoding="utf-8")
        block = re.search(r"DEFAULT_ADDONS = \((.*?)\n\)", spec, re.S)[1]
        assert set(re.findall(r'"([a-z-]+)"', block)) == DEFAULT_ADDONS
        assert 'contents_directory="lib"' in spec
        for name in ("vethuq_interactive_cli", "tkinter", "vethuq_ui"):
            assert f'"{name}"' in spec

    def test_core_installs_the_same_add_ons_by_default(self):
        core = tomllib.loads((ROOT / "packages" / "core" / "pyproject.toml").read_text("utf-8"))
        installed = {
            re.match(r"vethuq-addon-([a-z-]+)", d)[1]
            for d in core["project"]["dependencies"]
            if d.startswith("vethuq-addon-") and not d.startswith("vethuq-addon-api")
        }
        assert installed == DEFAULT_ADDONS
        assert NOT_DEFAULT.isdisjoint(installed)
        extras = core["project"]["optional-dependencies"]
        for name in ("lexical", "proximity", "fuzzy", "noise-fuzzy"):
            assert extras[name] == [f"vethuq-addon-{name}~=0.1"]


class TestRelease:
    @pytest.mark.parametrize(
        ("text", "debian", "numeric", "display"),
        [
            ("1.2.0", "1.2.0", "1.2.0.0", "1.2.0"),
            ("1.2.0-rc1", "1.2.0~rc1", "1.2.0.0", "1.2.0-rc1"),
            ("1.2.0rc3", "1.2.0~rc3", "1.2.0.0", "1.2.0-rc3"),
        ],
    )
    def test_versions(self, text, debian, numeric, display):
        version = release.Version(text)
        assert (version.debian, version.numeric, version.display) == (debian, numeric, display)

    @pytest.mark.parametrize("text", ["", "1.2", "v1.2.0", "1.2.0-dev.1", "x"])
    def test_a_bad_version_is_refused(self, text):
        with pytest.raises(release.ReleaseError):
            release.Version(text)

    @pytest.mark.skipif(shutil.which("dpkg") is None, reason="needs dpkg")
    def test_a_release_candidate_sorts_before_the_release_in_debian(self):
        older, newer = release.Version("1.2.0-rc1").debian, release.Version("1.2.0").debian
        compare = subprocess.run(["dpkg", "--compare-versions", older, "lt", newer])  # noqa: S603, S607
        assert compare.returncode == 0

    def test_a_mode_is_required(self):
        with pytest.raises(SystemExit):
            release.main([])

    def test_the_control_file(self):
        control = release.Cli(release.Version("1.2.0-rc1")).control("amd64", 42)
        assert "Package: vethuq-cli\nVersion: 1.2.0~rc1\n" in control
        assert "Architecture: amd64\n" in control and "Installed-Size: 42\n" in control
        assert control.endswith("\n")

    def test_the_cli_tag_is_planned_and_does_not_look_like_the_core_tag(self):
        result = plan.plan("vethuq-cli-v1.2.0-rc1")
        assert (result.dist, result.directory, result.prerelease) == (
            "vethuq-cli",
            "packages/cli",
            True,
        )
        assert plan.plan("vethuq-v1.2.0").dist == "vethuq"

    def test_the_cli_version_comes_from_its_own_tags(self):
        project = tomllib.loads((ROOT / "packages" / "cli" / "pyproject.toml").read_text("utf-8"))
        raw = project["tool"]["hatch"]["version"]["raw-options"]
        pattern = re.compile(raw["tag_regex"])
        assert pattern.match("vethuq-cli-v1.2.0")["version"] == "1.2.0"
        assert not pattern.match("vethuq-v1.2.0")
        assert "vethuq-cli-v*" in raw["git_describe_command"]


IC_INSTALLER = ROOT / "packages" / "interactive-cli" / "installer"


class TestInteractiveInstaller:
    """vethuqic.exe goes into the command line's folder and reuses its lib/ and add-ons/."""

    def script(self) -> str:
        return (IC_INSTALLER / "vethuqic.iss").read_text(encoding="utf-8")

    def test_it_uses_the_shared_images_license_and_icon(self):
        script = self.script()
        for name in ("LICENSE.rtf", "vethuq.ico", "wizard_large.bmp", "wizard_small.bmp"):
            assert f"..\\..\\..\\installer\\shared\\{name}" in script
            assert (SHARED / name).is_file()

    def test_it_installs_only_the_shell_into_the_cli_folder(self):
        script = self.script()
        files = script.split("[Files]")[1].split("[")[0]
        assert re.findall(r"^Source: .*", files, re.M) == [
            'Source: "..\\..\\..\\build\\cli\\vethuq\\{#MyAppExeName}"; '
            'DestDir: "{app}"; Flags: ignoreversion'
        ]
        assert '#define MyAppExeName "vethuqic.exe"' in script
        assert "DefaultDirName={code:CliDir}" in script
        shared = (SHARED / "into_cli_folder.iss").read_text(encoding="utf-8")
        assert "InstallLocation" in shared and "runtime-id.txt" in shared
        # The AppId of the command line, to find its folder; its own AppId differs.
        cli = (INSTALLER / "vethuq-cli.iss").read_text(encoding="utf-8")
        cli_id = re.search(r"^AppId=\{\{([0-9A-F-]+)\}", cli, re.M)[1]
        assert f'#define CliAppId "{cli_id}"' in script
        assert f"AppId={{{{{cli_id}}}" not in script

    def test_the_cli_uninstaller_removes_the_shell(self):
        cli = (INSTALLER / "vethuq-cli.iss").read_text(encoding="utf-8")
        assert 'Name: "{app}\\vethuqic.exe"' in cli

    def test_the_spec_is_not_git_ignored(self):
        # *.spec is ignored in .gitignore; the spec must be un-ignored or CI never sees it.
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "!installer/shared/vethuq.spec" in ignore

    def test_the_spec_builds_both_programs_into_one_folder(self):
        spec = (SHARED / "vethuq.spec").read_text(encoding="utf-8")
        assert '_exe_for(INSTALLER / "vethuq_entry.py", "vethuq"' in spec
        assert 'IC_INSTALLER / "vethuqic_entry.py",\n    "vethuqic"' in spec
        assert 'SHARED / "addons_hook.py"' in spec
        assert spec.count("COLLECT(") == 1
        # The command line has no shell in it.
        assert "CLI_EXCLUDES" in spec and '"questionary"' in spec

    def test_the_interactive_tag_is_planned_and_versions_come_from_it(self):
        result = plan.plan("vethuq-interactive-cli-v1.2.0")
        assert (result.dist, result.directory) == (
            "vethuq-interactive-cli",
            "packages/interactive-cli",
        )
        assert plan.plan("vethuq-cli-v1.2.0").dist == "vethuq-cli"
        project = tomllib.loads(
            (ROOT / "packages" / "interactive-cli" / "pyproject.toml").read_text("utf-8")
        )
        raw = project["tool"]["hatch"]["version"]["raw-options"]
        assert re.match(raw["tag_regex"], "vethuq-interactive-cli-v1.2.0-rc1")
        assert "vethuq-interactive-cli-v*" in raw["git_describe_command"]

    def test_the_deb_checks_the_runtime_and_depends_on_the_cli(self):
        postinst = release.Cli.postinst("vethuq-interactive-cli")
        assert "/usr/share/vethuq-interactive-cli/runtime-id" in postinst and "exit 1" in postinst
        control = release.Cli(release.Version("1.2.0")).control(
            "amd64", 1, package="vethuq-interactive-cli", depends="vethuq-cli"
        )
        assert "Package: vethuq-interactive-cli\n" in control
        assert "Depends: vethuq-cli\n" in control
        assert "Terminal=true" in release.Cli.DESKTOP

    @pytest.mark.parametrize("package", ["vethuq-cli", "vethuq-interactive-cli"])
    def test_every_control_line_is_a_field_or_a_continuation(self, package):
        control = release.Cli(release.Version("1.2.0")).control("amd64", 1, package=package)
        for line in control.splitlines():
            assert line.startswith(" ") or re.match(r"^[A-Za-z-]+: ", line), line

    def test_a_mode_is_still_required(self):
        with pytest.raises(SystemExit):
            release.main(["--dev"])


BS_INSTALLER = ROOT / "packages" / "background" / "installer"


class TestBackgroundInstaller:
    """vethuqbs.exe goes into the command line's folder, like the interactive shell."""

    def script(self) -> str:
        return (BS_INSTALLER / "vethuqbs.iss").read_text(encoding="utf-8")

    @pytest.mark.parametrize("name", ["vethuqbs.iss", "vethuqbs_entry.py", "AFTER_INSTALL.txt"])
    def test_the_file_exists(self, name):
        assert (BS_INSTALLER / name).is_file()

    def test_it_uses_the_shared_images_license_and_icon_and_cli_folder_code(self):
        script = self.script()
        for name in ("LICENSE.rtf", "vethuq.ico", "wizard_large.bmp", "wizard_small.bmp"):
            assert f"..\\..\\..\\installer\\shared\\{name}" in script
        assert 'include "..\\..\\..\\installer\\shared\\into_cli_folder.iss"' in script
        assert "DefaultDirName={code:CliDir}" in script
        assert (SHARED / "into_cli_folder.iss").is_file()
        # Its own AppId, and the CLI's to find the folder.
        cli = (INSTALLER / "vethuq-cli.iss").read_text(encoding="utf-8")
        cli_id = re.search(r"^AppId=\{\{([0-9A-F-]+)\}", cli, re.M)[1]
        assert f'#define CliAppId "{cli_id}"' in script
        assert f"AppId={{{{{cli_id}}}" not in script

    def test_it_installs_the_service_and_the_commands_only(self):
        files = self.script().split("[Files]")[1].split("[Code]")[0]
        sources = re.findall(r"^Source: .*", files, re.M)
        assert len(sources) == 2
        assert "{#MyAppExeName}" in sources[0] and "background-plugin" in sources[1]
        assert '#define MyAppExeName "vethuqbs.exe"' in self.script()

    def test_setup_does_not_create_the_service_but_cleans_up_after_it(self):
        script = self.script()
        assert "sc.exe" in script and "' + ServiceName" in script
        assert "RunSc('delete ' + ServiceName)" in script
        # Creating it needs a password and admin rights: left to `vethuq background install`.
        assert "RunSc('create" not in script
        assert "vethuq background install" in (BS_INSTALLER / "AFTER_INSTALL.txt").read_text()

    def test_the_shell_and_the_service_share_the_cli_folder_code(self):
        shell = (IC_INSTALLER / "vethuqic.iss").read_text(encoding="utf-8")
        assert "into_cli_folder.iss" in shell
        assert "FindCli" not in shell.split("[Code]")[1].split("#include")[1].split("\n", 1)[1]

    def test_the_spec_imports_what_it_uses(self):
        spec = (SHARED / "vethuq.spec").read_text(encoding="utf-8")
        for module in ("os", "re", "sys", "importlib.util", "importlib.metadata"):
            if re.search(rf"\b{re.escape(module.split('.')[0])}\.", spec):
                assert re.search(rf"^import {re.escape(module)}", spec, re.M) or (
                    module == "importlib.util" and "import importlib.util" in spec
                ), module

    def test_the_spec_builds_the_service_too_and_stages_the_commands(self):
        spec = (SHARED / "vethuq.spec").read_text(encoding="utf-8")
        assert 'BS_INSTALLER / "vethuqbs_entry.py"' in spec and '"vethuqbs"' in spec
        assert "add-ons/background/vethuq_background" in spec
        assert spec.count("COLLECT(") == 1
        for module in ("servicemanager", "win32serviceutil"):
            assert f'"{module}"' in spec

    def test_the_command_line_installers_leave_the_service_alone(self):
        cli = (INSTALLER / "vethuq-cli.iss").read_text(encoding="utf-8")
        assert 'Name: "{app}\\vethuqbs.exe"' in cli
        assert release.PLUGIN.name == "background-plugin"

    def test_the_tag_is_planned_and_versions_come_from_it(self):
        result = plan.plan("vethuq-background-service-v1.2.0-rc1")
        assert (result.dist, result.directory, result.prerelease) == (
            "vethuq-background",
            "packages/background",
            True,
        )
        project = tomllib.loads(
            (ROOT / "packages" / "background" / "pyproject.toml").read_text("utf-8")
        )
        raw = project["tool"]["hatch"]["version"]["raw-options"]
        assert re.match(raw["tag_regex"], "vethuq-background-service-v1.2.0")
        assert "vethuq-background-service-v*" in raw["git_describe_command"]

    def test_the_deb_checks_the_runtime_and_depends_on_the_cli(self):
        postinst = release.Cli.postinst("vethuq-background-service")
        assert "/usr/share/vethuq-background-service/runtime-id" in postinst
        control = release.Cli(release.Version("1.2.0")).control(
            "amd64", 1, package="vethuq-background-service", depends="vethuq-cli"
        )
        assert (
            "Package: vethuq-background-service\n" in control and "Depends: vethuq-cli\n" in control
        )

    def test_a_mode_is_required(self):
        with pytest.raises(SystemExit):
            release.main(["--dev"])


W_INSTALLER = ROOT / "packages" / "worker" / "installer"


class TestWorkerInstaller:
    """vethuqw.exe goes into the command line's folder, like the shell and the service."""

    def script(self) -> str:
        return (W_INSTALLER / "vethuqw.iss").read_text(encoding="utf-8")

    @pytest.mark.parametrize("name", ["vethuqw.iss", "vethuqw_entry.py"])
    def test_the_file_exists(self, name):
        assert (W_INSTALLER / name).is_file()

    def test_it_installs_only_the_worker_into_the_cli_folder(self):
        script = self.script()
        files = script.split("[Files]")[1].split("[Code]")[0]
        assert len(re.findall(r"^Source: .*", files, re.M)) == 1
        assert '#define MyAppExeName "vethuqw.exe"' in script
        assert "DefaultDirName={code:CliDir}" in script
        assert "into_cli_folder.iss" in script
        for name in ("LICENSE.rtf", "vethuq.ico", "wizard_large.bmp", "wizard_small.bmp"):
            assert f"..\\..\\..\\installer\\shared\\{name}" in script

    def test_every_installer_has_an_app_id_of_its_own(self):
        ids = []
        for path in (
            INSTALLER / "vethuq-cli.iss",
            IC_INSTALLER / "vethuqic.iss",
            BS_INSTALLER / "vethuqbs.iss",
            W_INSTALLER / "vethuqw.iss",
        ):
            ids.append(re.search(r"^AppId=\{\{([0-9A-Fa-f-]+)\}", path.read_text("utf-8"), re.M)[1])
        assert len(set(ids)) == 4

    def test_the_spec_builds_the_worker_with_its_schemas(self):
        spec = (SHARED / "vethuq.spec").read_text(encoding="utf-8")
        assert 'W_INSTALLER / "vethuqw_entry.py"' in spec and '"vethuqw"' in spec
        assert '"jsonschema_specifications"' in spec and '"vethuq_worker"' in spec
        assert spec.count("COLLECT(") == 1

    def test_the_command_line_installers_leave_the_worker_alone(self):
        cli = (INSTALLER / "vethuq-cli.iss").read_text(encoding="utf-8")
        assert 'Name: "{app}\\vethuqw.exe"' in cli

    def test_its_tag_does_not_clash_with_the_pypi_one(self):
        binary = plan.plan("vethuq-worker-bin-v1.2.0-rc1")
        assert (binary.dist, binary.prerelease) == ("vethuq-worker", True)
        # The PyPI release keeps its tag, which the program's tag does not match.
        assert plan.plan("vethuq-worker-v1.2.0").version == "1.2.0"
        release_yml = (ROOT / ".github" / "workflows" / "release.yml").read_text("utf-8")
        assert '"vethuq-worker-v*"' in release_yml
        assert not re.match(r"vethuq-worker-v.*", "vethuq-worker-bin-v1.2.0")

    def test_the_deb_checks_the_runtime_and_depends_on_the_cli(self):
        assert "/usr/share/vethuq-worker/runtime-id" in release.Cli.postinst("vethuq-worker")

    def test_a_mode_is_required(self):
        with pytest.raises(SystemExit):
            release.main(["--dev"])


ADDON_INSTALLER = ROOT / "installer" / "addon"


class TestAddOnInstaller:
    """One installer per add-on: into VethuQ's add-ons/ folder, and only if VethuQ is there."""

    def script(self) -> str:
        return (ADDON_INSTALLER / "vethuq-addon.iss").read_text(encoding="utf-8")

    def test_it_uses_the_shared_images_and_license(self):
        script = self.script()
        for name in ("LICENSE.rtf", "vethuq.ico", "wizard_large.bmp", "wizard_small.bmp"):
            assert f"..\\shared\\{name}" in script
            assert (SHARED / name).is_file()

    def test_it_installs_into_the_add_ons_folder_of_vethuq(self):
        script = self.script()
        assert 'DestDir: "{app}\\add-ons\\{#AddonName}"' in script
        assert "DefaultDirName={code:VethuqDir}" in script
        assert "PrivilegesRequiredOverridesAllowed=dialog commandline" in script

    def test_it_stops_unless_the_command_line_the_shell_or_the_desktop_app_is_installed(self):
        script = self.script()
        assert (
            "InstallLocation(CliKey) or InstallLocation(ShellKey) or InstallLocation(DesktopKey)"
            in script
        )
        assert "VethuQ is not installed. Install VethuQ first" in script
        for path, key in (
            (INSTALLER / "vethuq-cli.iss", "CliKey"),
            (IC_INSTALLER / "vethuqic.iss", "ShellKey"),
        ):
            app_id = re.search(r"^AppId=\{\{([0-9A-F-]+)\}", path.read_text("utf-8"), re.M)[1]
            assert f"{key} = '{{{app_id}}}_is1'" in script

    def test_it_asks_for_no_licence(self):
        script = self.script().lower()
        assert "licence" not in script.split("[code]")[1]
        assert "[run]" not in script

    def test_the_app_id_is_the_add_ons_own(self):
        a = release.AddOn("xls", release.Version("1.0.0"), ROOT).guid
        b = release.AddOn("docx", release.Version("1.0.0"), ROOT).guid
        assert a == release.AddOn("xls", release.Version("2.0.0"), ROOT).guid
        assert a != b and re.fullmatch(r"[0-9A-F-]{36}", a)

    def test_the_cli_installers_ids_are_not_reused(self):
        ids = {
            release.AddOn(n, release.Version("1.0.0"), ROOT).guid for n in ("xls", "docx", "telugu")
        }
        cli = (INSTALLER / "vethuq-cli.iss").read_text("utf-8")
        assert not any(guid in cli for guid in ids)

    def test_the_tag_names_the_add_on(self):
        result = plan.plan("vethuq-addon-xls-v1.2.0-rc1")
        assert (result.name, result.dist, result.prerelease) == ("xls", "vethuq-addon-xls", True)
        assert plan.plan("vethuq-addon-ocr-quick-v1.0.0").name == "ocr-quick"
        # The add-on API package keeps its own tag.
        assert plan.plan("vethuq-addon-api-v0.1.0").name == ""
        with pytest.raises(plan.ReleaseError):
            plan.plan("vethuq-addon-core-v1.0.0")
        workflow = (ROOT / ".github" / "workflows" / "release-add-on.yml").read_text("utf-8")
        assert '"!vethuq-addon-api-v*"' in workflow

    def test_pins_are_read_from_an_export_and_names_are_normalised(self):
        text = "numpy==2.1.0 ; sys_platform == 'win32'\n# comment\nPyYAML==6.0\n-e ./x\n"
        text += "olefile==0.47\n"
        assert release.AddOn.pins(text) == {"numpy": "2.1.0", "pyyaml": "6.0", "olefile": "0.47"}
        assert release.normalise("Typing_Extensions") == "typing-extensions"

    def test_the_wheels_own_requirements_leave_out_vethuq_and_extras(self, tmp_path):
        import zipfile

        wheel = tmp_path / "x-1.0-py3-none-any.whl"
        metadata = (
            "Requires-Dist: vethuq-addon-api~=0.1\nRequires-Dist: olefile>=0.46\n"
            "Requires-Dist: pillow>=10; sys_platform != 'x'\n"
            "Requires-Dist: pytest; extra == 'test'\n"
        )
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr("x-1.0.dist-info/METADATA", metadata)
        assert release.AddOn.requirements(wheel) == [
            "olefile>=0.46",
            "pillow>=10; sys_platform != 'x'",
        ]

    def test_the_add_on_is_found_in_the_premium_layout(self, tmp_path):
        folder = tmp_path / "packages" / "add-ons" / "file-types" / "xls"
        (folder / "src" / "vethuq_addon_xls").mkdir(parents=True)
        (folder / "pyproject.toml").write_text('[project]\nname = "vethuq-addon-xls"\n')
        addon = release.AddOn("xls", release.Version("1.0.0"), tmp_path)
        assert addon.source() == folder
        with pytest.raises(release.ReleaseError, match="No add-on 'nope'"):
            release.AddOn("nope", release.Version("1.0.0"), tmp_path).source()

    def test_the_wheel_must_be_the_tags_version(self, tmp_path):
        addon = release.AddOn("xls", release.Version("1.2.0-rc1"), tmp_path)
        addon.check_version(Path("vethuq_addon_xls-1.2.0rc1-cp311-abi3-win_amd64.whl"))
        with pytest.raises(release.ReleaseError, match="set the add-on's version"):
            addon.check_version(Path("vethuq_addon_xls-0.1.0-cp311-abi3-win_amd64.whl"))

    def test_the_deb_refuses_to_install_without_vethuq(self):
        assert "/opt/vethuq/vethuq" in release.AddOn.PREINST and "exit 1" in release.AddOn.PREINST
        assert "Install vethuq-cli first" in release.AddOn.PREINST

    def test_it_needs_a_name(self):
        with pytest.raises(SystemExit):
            release.main(["--add-on"])
