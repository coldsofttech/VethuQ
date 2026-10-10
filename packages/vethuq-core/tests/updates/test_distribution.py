import pytest
from vethuq_core.updates import Distribution, Versions


class TestCurrent:
    def test_pip_unless_frozen(self, monkeypatch):
        monkeypatch.delattr("sys.frozen", raising=False)
        assert Distribution.current() == Distribution.PIP

    def test_desktop_when_frozen(self, monkeypatch):
        monkeypatch.setattr("sys.frozen", True, raising=False)
        assert Distribution.current() == Distribution.DESKTOP


class TestDesktopVersion:
    def test_reads_the_stamp(self, tmp_path):
        (tmp_path / Distribution.STAMP_FILENAME).write_text(" 1.4.0 \n", encoding="utf-8")

        assert Distribution.desktop_version(tmp_path) == "1.4.0"

    @pytest.mark.parametrize("content", [None, "", "\n"])
    def test_no_stamp_means_none(self, tmp_path, content):
        if content is not None:
            (tmp_path / Distribution.STAMP_FILENAME).write_text(content, encoding="utf-8")

        assert Distribution.desktop_version(tmp_path) is None

    def test_missing_package_means_none(self, monkeypatch):
        def missing(_name):
            raise ModuleNotFoundError

        monkeypatch.setattr("vethuq_core.updates.distribution.resources.files", missing)

        assert Distribution.desktop_version() is None


class TestInstalled:
    def test_desktop_uses_the_installer_version_not_package_metadata(self, monkeypatch):
        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr(
            Distribution, "desktop_version", staticmethod(lambda root=None: "2.0.1")
        )

        assert Versions.installed() == "2.0.1"

    def test_desktop_without_a_stamp_is_unknown(self, monkeypatch):
        monkeypatch.setattr("sys.frozen", True, raising=False)
        monkeypatch.setattr(Distribution, "desktop_version", staticmethod(lambda root=None: None))

        assert Versions.installed() == "unknown"

    def test_pip_uses_the_package_version(self, monkeypatch):
        monkeypatch.delattr("sys.frozen", raising=False)
        monkeypatch.setattr(
            "vethuq_core.version.VersionInfo.vethuq_version", staticmethod(lambda: "1.3.0")
        )

        assert Versions.installed() == "1.3.0"
