import json
from pathlib import Path

import pytest
from vethuq_core.filetypes import FileType, FileTypes
from vethuq_core.paths import Paths
from vethuq_core.readers import Readers
from vethuq_core.settings.filetypes import FileTypeSettings
from vethuq_core.storage import open_storage
from vethuq_core.version import VersionInfo


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setattr(Paths, "default_data_root", staticmethod(lambda: tmp_path))
    return tmp_path


@pytest.fixture
def storage(tmp_path):
    store = open_storage(tmp_path / "vethuq.db")
    yield store
    store.close()


def _pretend_missing(monkeypatch, module: str):
    real = FileType.is_installed

    def is_installed(self):
        return False if module in self.modules else real(self)

    monkeypatch.setattr(FileType, "is_installed", is_installed)


class TestManifests:
    def test_every_type_folder_has_a_manifest_naming_its_reader(self):
        assert {t.id for t in FileTypes.all()} >= {"pdf", "png", "jpg"}
        for file_type in FileTypes.all():
            assert file_type.extra == f"type-{file_type.id}"
            assert file_type.load_reader().file_type

    def test_extension_lookup_is_case_insensitive(self):
        assert FileTypes.for_extension(".PDF").id == "pdf"
        assert FileTypes.for_extension(".nope") is None

    def test_pdf_is_the_default_type(self):
        assert [t.id for t in FileTypes.all() if t.default] == ["pdf"]


class TestInstalledAndEnabled:
    def test_type_whose_dependency_is_missing_is_not_installed(self, monkeypatch):
        _pretend_missing(monkeypatch, "pymupdf")
        assert "pdf" not in {t.id for t in FileTypes.installed()}
        assert "pdf" in {t.id for t in FileTypes.missing()}
        assert "pip install vethuq[type-pdf]" in FileTypes.unavailable_reason(FileTypes.get("pdf"))

    def test_everything_installed_is_enabled_without_a_selection(self, data_root):
        assert FileTypes.selection() is None
        assert {t.id for t in FileTypes.enabled()} == {t.id for t in FileTypes.installed()}

    def test_selection_limits_enabled_types(self, data_root):
        FileTypes.save_selection(["pdf"])
        assert [t.id for t in FileTypes.enabled()] == ["pdf"]
        assert "not enabled" in FileTypes.unavailable_reason(FileTypes.get("png"))

    def test_unreadable_selection_is_ignored(self, data_root):
        (data_root / FileTypes.SELECTION_FILENAME).write_text("{oops", encoding="utf-8")
        assert FileTypes.selection() is None


class TestReaderRegistry:
    def test_unavailable_type_is_explained_instead_of_called_unsupported(self, monkeypatch):
        _pretend_missing(monkeypatch, "pymupdf")
        monkeypatch.setattr(Readers, "_BY_SUFFIX", {})
        monkeypatch.setattr(Readers, "_loaded", True)
        assert Readers.unavailable_type(Path("a.pdf")).id == "pdf"
        assert "pip install vethuq[type-pdf]" in Readers.unsupported_reason(Path("a.pdf"))

    def test_unknown_extension_stays_unsupported(self):
        assert Readers.unavailable_type(Path("a.xyz")) is None
        assert Readers.unsupported_reason(Path("a.xyz")) == "Unsupported file format: .xyz"


class TestRecordedInDatabase:
    def test_record_installed_stores_the_type_extras(self, storage):
        assert FileTypeSettings.get_installed(storage) == []
        recorded = FileTypeSettings.record_installed(storage)
        assert recorded == [t.extra for t in FileTypes.installed()]
        assert FileTypeSettings.get_installed(storage) == recorded
        assert json.loads(storage.get_setting_value("installed_file_types")) == recorded

    def test_version_lists_installed_type_packages(self):
        rows = dict(VersionInfo.rows())
        assert "type-pdf" in rows["File types"]
