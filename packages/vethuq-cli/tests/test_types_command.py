import json

from typer.testing import CliRunner
from vethuq_cli.console import console
from vethuq_cli.main import app
from vethuq_core.filetypes import FileType
from vethuq_core.storage import open_storage

runner = CliRunner()


def _missing_pdf(monkeypatch):
    real = FileType.is_installed
    monkeypatch.setattr(
        FileType, "is_installed", lambda self: False if self.id == "pdf" else real(self)
    )


class TestTypesList:
    def test_lists_installed_types_only_by_default(self, use_temp_db, monkeypatch):
        use_temp_db()
        _missing_pdf(monkeypatch)
        result = runner.invoke(app, ["file-types", "list"])
        assert result.exit_code == 0
        assert "PNG image" in result.output
        assert "PDF" not in result.output

    def test_all_adds_missing_types_with_install_hints(self, use_temp_db, monkeypatch):
        use_temp_db()
        _missing_pdf(monkeypatch)
        monkeypatch.setattr(console, "width", 200)  # keep the install hint on one line
        result = runner.invoke(app, ["file-types", "list", "--all"])
        assert result.exit_code == 0
        assert "not installed" in result.output
        assert "pip install vethuq[type-pdf]" in result.output


class TestVersion:
    def test_shows_and_stores_installed_type_packages(self, use_temp_db):
        db_path = use_temp_db()
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "type-pdf" in result.output
        storage = open_storage(db_path)
        try:
            stored = json.loads(storage.get_setting_value("installed_file_types"))
        finally:
            storage.close()
        assert "type-pdf" in stored
