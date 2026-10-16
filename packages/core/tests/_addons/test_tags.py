"""Add-ons built for another Python or platform are refused with a message, not imported."""

from __future__ import annotations

import sys
from importlib.metadata import distributions

import pytest
from packaging.tags import Tag, sys_tags

from tests.addons_factory import AddonFactory
from vethuq._addons.manager import _AddonManager
from vethuq._addons.tags import _WheelTags
from vethuq.enums import AddonStatus

PLATFORM = next(iter(sys_tags())).platform


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "vethuq.db"


def wheel(*tags: str) -> str:
    return "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: false\n" + "".join(
        f"Tag: {tag}\n" for tag in tags
    )


class _Dist:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def read_text(self, name: str) -> str | None:
        return self.text if name == "WHEEL" else None


class TestProblem:
    RUNNING = [Tag("cp311", "cp311", "win_amd64"), Tag("cp311", "abi3", "win_amd64")]

    def problem(self, text: str | None):
        return _WheelTags.problem(_Dist(text), self.RUNNING)  # type: ignore[arg-type]

    def test_no_wheel_file_is_never_a_problem(self):
        assert self.problem(None) is None
        assert _WheelTags.problem(None) is None

    def test_a_matching_wheel_passes(self):
        assert self.problem(wheel("cp311-cp311-win_amd64")) is None

    def test_abi3_built_for_an_older_python_passes(self):
        assert self.problem(wheel("cp311-abi3-win_amd64")) is None

    def test_a_pure_python_wheel_passes_when_the_tag_is_supported(self):
        running = [*self.RUNNING, Tag("py3", "none", "any")]
        assert _WheelTags.problem(_Dist(wheel("py3-none-any")), running) is None  # type: ignore[arg-type]

    def test_the_wrong_platform_is_named(self):
        message = self.problem(wheel("cp311-abi3-manylinux_2_28_x86_64"))
        assert message is not None and message.startswith("built for Linux; VethuQ is running on")

    def test_the_wrong_python_is_named(self):
        message = self.problem(wheel("cp312-cp312-win_amd64"))
        here = f"{sys.version_info[0]}.{sys.version_info[1]}"
        assert message == f"built for Python 3.12; VethuQ is running Python {here}"

    def test_compressed_tags_are_expanded(self):
        assert _WheelTags.of(_Dist(wheel("cp311-abi3.cp311-win_amd64.win32")))  # type: ignore[arg-type]
        assert len(_WheelTags.of(_Dist(wheel("cp311-abi3.cp311-win_amd64.win32")))) == 4  # type: ignore[arg-type]

    def test_a_malformed_tag_line_is_skipped(self):
        assert _WheelTags.of(_Dist("Tag: nonsense\n")) == frozenset()  # type: ignore[arg-type]


class TestManager:
    def manager(self, folder, db_path) -> _AddonManager:
        def discover():
            return [
                point
                for dist in distributions(path=[str(folder)])
                for point in dist.entry_points
                if point.group == "vethuq.addons"
            ]

        return _AddonManager(db_path, lambda: None, discover=discover)

    def install(self, tmp_path, monkeypatch, tag: str | None, **kwargs) -> str:
        monkeypatch.setattr(sys, "path", list(sys.path))
        folder = tmp_path / "site"
        folder.mkdir()
        module = AddonFactory.install(folder, **kwargs)
        if tag is not None:
            (folder / f"{module}-1.2.3.dist-info" / "WHEEL").write_text(wheel(tag))
        return module

    def status(self, tmp_path, db_path):
        item = self.manager(tmp_path / "site", db_path).loaded()["dummy"]
        return item.status, item.detail

    def test_a_wrong_platform_is_incompatible_and_never_imported(
        self, tmp_path, monkeypatch, db_path
    ):
        module = self.install(tmp_path, monkeypatch, "cp311-abi3-plan9_1")
        try:
            status, detail = self.status(tmp_path, db_path)
            assert status is AddonStatus.INCOMPATIBLE
            assert detail.startswith("built for plan9_1; VethuQ is running on")
            assert module not in sys.modules
        finally:
            AddonFactory.forget(module)

    def test_a_wrong_python_is_incompatible(self, tmp_path, monkeypatch, db_path):
        module = self.install(tmp_path, monkeypatch, f"cp399-cp399-{PLATFORM}")
        try:
            status, detail = self.status(tmp_path, db_path)
            assert status is AddonStatus.INCOMPATIBLE and "Python 3.99" in detail
        finally:
            AddonFactory.forget(module)

    def test_abi3_for_this_platform_loads(self, tmp_path, monkeypatch, db_path):
        module = self.install(tmp_path, monkeypatch, f"cp311-abi3-{PLATFORM}")
        try:
            assert self.status(tmp_path, db_path)[0] is AddonStatus.LOADED
        finally:
            AddonFactory.forget(module)

    def test_an_install_without_a_wheel_file_loads(self, tmp_path, monkeypatch, db_path):
        module = self.install(tmp_path, monkeypatch, None)
        try:
            assert self.status(tmp_path, db_path)[0] is AddonStatus.LOADED
        finally:
            AddonFactory.forget(module)

    def test_an_import_error_after_a_passing_check_names_the_folder(
        self, tmp_path, monkeypatch, db_path
    ):
        module = self.install(
            tmp_path, monkeypatch, f"cp311-abi3-{PLATFORM}", target="no_such_module_xyz:Nope"
        )
        try:
            status, detail = self.status(tmp_path, db_path)
            assert status is AddonStatus.FAILED
            assert "no_such_module_xyz" in detail and f"(in {tmp_path / 'site'}" in detail
        finally:
            AddonFactory.forget(module)

    def test_a_corrupt_addon_is_reported_not_fatal(self, tmp_path, monkeypatch, db_path):
        module = self.install(tmp_path, monkeypatch, f"cp311-abi3-{PLATFORM}")
        (tmp_path / "site" / f"{module}.py").write_text("raise SystemError('corrupt')\n")
        try:
            status, detail = self.status(tmp_path, db_path)
            assert status is AddonStatus.FAILED and "corrupt" in detail
        finally:
            AddonFactory.forget(module)


@pytest.mark.parametrize("tag", ["win_amd64", "manylinux_2_28_x86_64", "macosx_11_0_arm64", "any"])
def test_platform_names(tag):
    assert _WheelTags.platform_name(tag) in {"Windows", "Linux", "macOS", "any platform"}
