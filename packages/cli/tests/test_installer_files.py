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
    @pytest.mark.parametrize(
        "name",
        [
            "vethuq-cli.spec",
            "vethuq-cli.iss",
            "vethuq_entry.py",
            "addons_hook.py",
            "LICENSE.rtf",
            "vethuq.ico",
            "wizard_large.bmp",
            "wizard_small.bmp",
        ],
    )
    def test_the_file_exists(self, name):
        assert (INSTALLER / name).is_file()

    def test_the_wizard_images_have_inno_sizes(self):
        assert Image.open(INSTALLER / "wizard_large.bmp").size == (164, 314)
        assert Image.open(INSTALLER / "wizard_small.bmp").size == (55, 55)

    def test_the_inno_script_uses_the_images_and_is_command_line_only(self):
        script = (INSTALLER / "vethuq-cli.iss").read_text(encoding="utf-8")
        for line in (
            "SetupIconFile=vethuq.ico",
            "WizardImageFile=wizard_large.bmp",
            "WizardSmallImageFile=wizard_small.bmp",
            "LicenseFile=LICENSE.rtf",
        ):
            assert line in script
        assert re.search(r"^Source: .*build\\cli\\vethuq\\lib\\", script, re.M)
        assert re.search(r"^Source: .*build\\cli\\vethuq\\add-ons\\", script, re.M)
        code = "\n".join(line for line in script.splitlines() if not line.startswith(";"))
        for word in ("VethuQ-UI", "worker", "[Icons]", "desktopicon", "interactive"):
            assert word not in code

    def test_the_spec_bakes_in_exactly_the_default_add_ons(self):
        spec = (INSTALLER / "vethuq-cli.spec").read_text(encoding="utf-8")
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
