"""Consumer-facing smoke tests for the merged `vethuq` package.

These exercise the public API documented in docs/PYTHON_API.md the way an installed
package would be used. The data root is redirected to a temp directory so nothing
touches the real local `vethuq.db`.
"""

import json
import sqlite3
from pathlib import Path

import pytest
import vethuq
from typer.testing import CliRunner


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> vethuq.Vethuq:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(
        "vethuq._core.paths.Paths.default_data_root", staticmethod(lambda: data_dir)
    )
    return vethuq.Vethuq()


@pytest.fixture
def docs_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "note.txt").write_text("placeholder", encoding="utf-8")
    return folder


def test_public_names_are_importable():
    for name in vethuq.__all__:
        assert hasattr(vethuq, name), name


def test_db_path_is_a_path():
    assert isinstance(vethuq.DB_PATH, Path)


# --- sources -----------------------------------------------------------------------------------


def test_sources_add_folder_and_list(client: vethuq.Vethuq, docs_folder: Path):
    source = client.sources.add(docs_folder)

    assert source.source_type == "folder"
    assert source.status == "pending"
    assert source.is_active
    assert Path(source.path) == docs_folder.resolve()

    assert [s.id for s in client.sources.list()] == [source.id]


def test_sources_add_file_accepts_str_path(client: vethuq.Vethuq, docs_folder: Path):
    source = client.sources.add(str(docs_folder / "note.txt"))

    assert source.source_type == "file"


def test_sources_add_missing_path_raises_source_path_error(client: vethuq.Vethuq, tmp_path: Path):
    with pytest.raises(vethuq.SourcePathError):
        client.sources.add(tmp_path / "does-not-exist")


def test_sources_add_duplicate_raises_source_already_exists_error(
    client: vethuq.Vethuq, docs_folder: Path
):
    client.sources.add(docs_folder)

    with pytest.raises(vethuq.SourceAlreadyExistsError):
        client.sources.add(docs_folder)


def test_sources_remove_by_id_and_by_path(client: vethuq.Vethuq, docs_folder: Path, tmp_path: Path):
    other = tmp_path / "other"
    other.mkdir()
    first = client.sources.add(docs_folder)
    second = client.sources.add(other)

    assert client.sources.remove(first.id).id == first.id
    assert client.sources.remove(other).id == second.id
    assert client.sources.list() == []


def test_sources_list_include_inactive_shows_removed(client: vethuq.Vethuq, docs_folder: Path):
    source = client.sources.add(docs_folder)
    client.sources.remove(source.id)

    assert client.sources.list() == []
    inactive = client.sources.list(include_inactive=True)
    assert [s.id for s in inactive] == [source.id]
    assert not inactive[0].is_active
    assert inactive[0].removed_at is not None


def test_sources_remove_unknown_raises_source_not_found_error(client: vethuq.Vethuq):
    with pytest.raises(vethuq.SourceNotFoundError):
        client.sources.remove(999)


def test_sources_files_lists_files_under_a_source(client, docs_folder, tmp_path):
    source = client.sources.add(docs_folder)
    assert client.sources.files(source.id) == []

    conn = sqlite3.connect(tmp_path / "data" / "db" / "vethuq.db")
    doc_id = conn.execute("INSERT INTO documents (created_at) VALUES ('2026-01-01')").lastrowid
    conn.execute(
        "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
        "VALUES (?, ?, ?, 'pdf', 'pending')",
        (source.id, doc_id, str(docs_folder / "a.pdf")),
    )
    conn.commit()
    conn.close()

    files = client.sources.files(docs_folder)
    assert [(f.file_path, f.status) for f in files] == [(str(docs_folder / "a.pdf"), "pending")]
    assert isinstance(files[0], vethuq.SourceFile)


def test_sources_files_unknown_source_raises(client):
    with pytest.raises(vethuq.SourceNotFoundError):
        client.sources.files(999)


def test_source_errors_share_a_base_class():
    for error in (
        vethuq.SourceAlreadyExistsError,
        vethuq.SourceNotFoundError,
        vethuq.SourcePathError,
    ):
        assert issubclass(error, vethuq.SourceError)


# --- settings ----------------------------------------------------------------------------------


def test_settings_defaults(client: vethuq.Vethuq):
    assert client.settings.gpu.is_enabled() is False
    assert client.settings.search.snippet.get() == 80
    assert client.settings.search.export_format.get() == "json"
    assert client.settings.search.engine.get() == "all"
    assert client.settings.search.case_sensitive.get() is False
    assert client.settings.index.removed_retention.get() == 7 * 24 * 60
    assert client.settings.ocr.retry.get() == 3
    assert client.settings.index.thread_workers.get() == "0"
    assert client.settings.index.stability_check.get() == 1.0
    assert client.settings.index.stale_lock.get() == "auto"
    assert client.settings.ocr.engine.get() == "quick"
    assert client.settings.db.integrity_check.get() == "auto"
    assert client.settings.db.integrity_check.get_interval_minutes() == 24 * 60


def test_db_integrity_check_passes_on_a_healthy_database(client: vethuq.Vethuq):
    result = client.db.integrity_check()

    assert isinstance(result, vethuq.IntegrityCheckResult)
    assert result.ok is True
    assert result.errors == []


def test_settings_gpu_enable_and_disable(client: vethuq.Vethuq):
    client.settings.gpu.enable()
    assert client.settings.gpu.is_enabled() is True

    client.settings.gpu.disable()
    assert client.settings.gpu.is_enabled() is False


def test_settings_values_round_trip(client: vethuq.Vethuq):
    client.settings.search.snippet.set(120)
    client.settings.search.export_format.set("html")
    client.settings.search.engine.set("full-text")
    client.settings.search.case_sensitive.set(True)
    client.settings.index.removed_retention.set(30)
    client.settings.ocr.retry.set(5)
    client.settings.index.thread_workers.set(vethuq.ThreadWorkersSettings.AUTO)
    client.settings.index.stability_check.set(0.5)
    client.settings.index.stale_lock.set("disable")
    client.settings.ocr.engine.set("deep")
    client.settings.db.integrity_check.set("disable")
    client.settings.db.integrity_check.set_interval_minutes(60)

    assert client.settings.search.snippet.get() == 120
    assert client.settings.search.export_format.get() == "html"
    assert client.settings.search.engine.get() == "full-text"
    assert client.settings.search.case_sensitive.get() is True
    assert client.settings.index.removed_retention.get() == 30
    assert client.settings.ocr.retry.get() == 5
    assert client.settings.index.thread_workers.get() == vethuq.ThreadWorkersSettings.AUTO
    assert client.settings.index.stability_check.get() == 0.5
    assert client.settings.index.stale_lock.get() == "disable"
    assert client.settings.ocr.engine.get() == "deep"
    assert client.settings.db.integrity_check.get() == "disable"
    assert client.settings.db.integrity_check.get_interval_minutes() == 60


def test_settings_accept_every_documented_choice(client: vethuq.Vethuq):
    for value in vethuq.SEARCH_EXPORT_FORMATS:
        client.settings.search.export_format.set(value)
    for value in vethuq.STALE_LOCK_VALUES:
        client.settings.index.stale_lock.set(value)
    for value in vethuq.OCR_ENGINE_MODES:
        client.settings.ocr.engine.set(value)
    for value in vethuq.INTEGRITY_CHECK_VALUES:
        client.settings.db.integrity_check.set(value)
    client.settings.index.thread_workers.set("0")
    client.settings.index.thread_workers.set(str(vethuq.ThreadWorkersSettings.MAX))


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.search.snippet.set(-1),
        lambda s: s.search.export_format.set("pdf"),
        lambda s: s.index.removed_retention.set(-1),
        lambda s: s.ocr.retry.set(-1),
        lambda s: s.index.thread_workers.set("not-a-number"),
        lambda s: s.index.stability_check.set(-1),
        lambda s: s.index.stale_lock.set("sometimes"),
        lambda s: s.ocr.engine.set("extreme"),
        lambda s: s.db.integrity_check.set("sometimes"),
        lambda s: s.db.integrity_check.set_interval_minutes(-1),
    ],
    ids=[
        "snippet",
        "export_format",
        "removed_retention",
        "ocr_retry",
        "thread_workers",
        "stability_check",
        "stale_lock",
        "engine",
        "integrity_check",
        "integrity_check_interval",
    ],
)
def test_settings_invalid_value_raises_invalid_setting_value_error(client: vethuq.Vethuq, call):
    with pytest.raises(vethuq.InvalidSettingValueError):
        call(client.settings)


def test_invalid_setting_error_is_a_settings_error_and_value_error():
    assert issubclass(vethuq.InvalidSettingValueError, vethuq.SettingsError)
    assert issubclass(vethuq.InvalidSettingValueError, ValueError)


# --- stats -------------------------------------------------------------------------------------


def test_stats_start_empty_and_reset_is_safe(client: vethuq.Vethuq):
    assert client.stats.processing() == []
    assert client.stats.confidence() == []

    client.stats.reset()

    assert client.stats.processing() == []
    assert client.stats.confidence() == []


# --- index -------------------------------------------------------------------------------------


def test_index_status_is_none_before_any_run(client: vethuq.Vethuq):
    assert client.index.status() is None


def test_index_status_for_source_with_no_documents_is_empty(
    client: vethuq.Vethuq, docs_folder: Path
):
    source = client.sources.add(docs_folder)

    assert client.index.status(source.id) == []
    assert client.index.status(str(source.id)) == []


def test_index_history_is_empty_before_any_run(client: vethuq.Vethuq, docs_folder: Path):
    source = client.sources.add(docs_folder)

    assert client.index.history() == []
    assert client.index.history(source.id, limit=5) == []


@pytest.mark.parametrize(
    "call",
    [
        lambda index: index.run("999"),
        lambda index: index.restart("999"),
        lambda index: index.status(999),
        lambda index: index.history(999),
    ],
    ids=["run", "restart", "status", "history"],
)
def test_index_unknown_target_raises_source_not_found_error(client: vethuq.Vethuq, call):
    with pytest.raises(vethuq.SourceNotFoundError):
        call(client.index)


@pytest.mark.parametrize("method", ["stop", "pause", "resume"])
def test_index_control_without_active_run_raises_index_runner_error(
    client: vethuq.Vethuq, method: str
):
    with pytest.raises(vethuq.IndexRunnerError):
        getattr(client.index, method)()


def test_index_errors_share_a_base_class():
    assert issubclass(vethuq.AlreadyRunningError, vethuq.IndexRunnerError)
    assert issubclass(vethuq.StaleLockError, vethuq.IndexRunnerError)


# --- search ------------------------------------------------------------------------------------


@pytest.fixture
def indexed_client(client: vethuq.Vethuq, tmp_path: Path) -> vethuq.Vethuq:
    """A client whose database already holds OCR'd pages (OCR itself isn't run here)."""
    db_file = tmp_path / "data" / "db" / "vethuq.db"
    client.sources.list()  # creates the database
    conn = sqlite3.connect(db_file)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO sources (path, source_type, status, added_at) "
        "VALUES ('/docs', 'folder', 'indexed', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, created_at) VALUES (1, '2026-01-01'), (2, '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
        "VALUES (1, 1, '/docs/invoice.pdf', 'pdf', 'indexed')"
    )
    conn.execute(
        "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
        "VALUES (1, 2, '/docs/scan.png', 'image', 'indexed')"
    )
    conn.execute(
        "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
        "VALUES (1, 1, 'Cover page', 0.9), (1, 2, 'Total due on this Invoice is 40 USD', 0.9)"
    )
    conn.execute(
        "INSERT INTO image_pages (document_id, ocr_text, confidence) "
        "VALUES (2, 'INVOICE copy for records', 0.9)"
    )
    conn.commit()
    conn.close()
    return client


def test_search_finds_matches_case_insensitively(indexed_client: vethuq.Vethuq):
    matches = indexed_client.search.run("invoice")

    assert [m.file_path for m in matches] == ["/docs/invoice.pdf", "/docs/scan.png"]
    pdf_match, image_match = matches
    assert (pdf_match.page_number, pdf_match.total_pages) == (2, 2)
    assert pdf_match.matched.lower() == "invoice"
    assert (image_match.page_number, image_match.total_pages) == (None, None)


def test_search_context_chars_limits_surrounding_text(indexed_client: vethuq.Vethuq):
    (match, _) = indexed_client.search.run("invoice", context_chars=5)

    assert len(match.before) <= 5
    assert len(match.after) <= 5
    assert match.truncated_before
    assert match.truncated_after


def test_search_exact_engine_matches_as_typed(indexed_client: vethuq.Vethuq):
    assert [m.matched for m in indexed_client.search.run("Invoice", engine="exact")] == ["Invoice"]
    assert indexed_client.search.run("invoice", engine="exact") == []


def test_search_full_text_engine_ranks_and_scores(indexed_client: vethuq.Vethuq):
    matches = indexed_client.search.run("invoices", engine="full-text")

    assert {m.file_path for m in matches} == {"/docs/invoice.pdf", "/docs/scan.png"}
    assert all(m.score is not None for m in matches)


def test_search_case_sensitive_applies_to_like(indexed_client: vethuq.Vethuq):
    matches = indexed_client.search.run("INVOICE", engine="like", case_sensitive=True)

    assert [m.file_path for m in matches] == ["/docs/scan.png"]


def test_search_uses_the_configured_engine(indexed_client: vethuq.Vethuq):
    indexed_client.settings.search.engine.set("exact")

    assert indexed_client.search.run("invoice") == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"engine": "nope"},
        {"engine": "full-text", "case_sensitive": True},
        {"engine": "exact", "case_sensitive": False},
    ],
)
def test_search_rejects_unusable_engine_options(indexed_client: vethuq.Vethuq, kwargs):
    with pytest.raises(vethuq.SearchOptionError):
        indexed_client.search.run("invoice", **kwargs)


def test_search_export_records_engine(indexed_client: vethuq.Vethuq, tmp_path: Path):
    matches = indexed_client.search.run("Invoice", engine="exact")

    path = indexed_client.search.export(
        matches, "Invoice", tmp_path / "out.json", "json", engine="exact", case_sensitive=True
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["engine"] == "exact"
    assert payload["case_sensitive"] is True


def test_search_without_matches_returns_empty_list(indexed_client: vethuq.Vethuq):
    assert indexed_client.search.run("no such text anywhere") == []


def test_search_export_json_and_html(indexed_client: vethuq.Vethuq, tmp_path: Path):
    matches = indexed_client.search.run("invoice")

    json_path = indexed_client.search.export(matches, "invoice", tmp_path / "out.json", "json")
    html_path = indexed_client.search.export(matches, "invoice", tmp_path / "out.html", "html")

    assert json_path == (tmp_path / "out.json").resolve()
    assert html_path == (tmp_path / "out.html").resolve()
    json.loads(json_path.read_text(encoding="utf-8"))
    assert "<html" in html_path.read_text(encoding="utf-8").lower()


def test_search_export_uses_configured_default_format(
    indexed_client: vethuq.Vethuq, tmp_path: Path
):
    indexed_client.settings.search.export_format.set("html")
    matches = indexed_client.search.run("invoice")

    path = indexed_client.search.export(matches, "invoice", tmp_path / "out.dat")

    assert "<html" in path.read_text(encoding="utf-8").lower()


def test_search_export_rejects_unknown_format(indexed_client: vethuq.Vethuq, tmp_path: Path):
    matches = indexed_client.search.run("invoice")

    with pytest.raises(ValueError):
        indexed_client.search.export(matches, "invoice", tmp_path / "out.pdf", "pdf")


# --- CLI ---------------------------------------------------------------------------------------


def test_cli_help_lists_commands():
    from vethuq._cli.main import app

    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("source", "index", "search", "settings", "stats"):
        assert command in result.output


def test_logs_tail_reads_a_component_log(client: vethuq.Vethuq, tmp_path: Path):
    log_dir = tmp_path / "data" / "logs"
    log_dir.mkdir(exist_ok=True)
    (log_dir / "index.log").write_text(
        "2026-10-01 10:00:00,000 INFO [MainThread] vethuq.index: from the log\n",
        encoding="utf-8",
    )

    assert client.logs.tail("index", 5) == [
        "2026-10-01 10:00:00,000 INFO [MainThread] vethuq.index: from the log"
    ]


def test_logs_tail_raises_when_there_is_no_log(client: vethuq.Vethuq):
    with pytest.raises(vethuq.LogNotFoundError):
        client.logs.tail("ui")


def test_db_backup_create_list_restore_and_delete(client: vethuq.Vethuq):
    client.db.integrity_check()

    info = client.db.backup_create("snap")
    assert info.name == "snap"
    assert "snap" in [b.name for b in client.db.backup_list()]

    safety = client.db.restore("snap")
    assert safety is not None and safety.kind == "safety"

    client.db.backup_delete("snap")
    assert "snap" not in [b.name for b in client.db.backup_list()]


def test_db_backup_rejects_bad_names(client: vethuq.Vethuq):
    client.db.integrity_check()

    with pytest.raises(vethuq.BackupError):
        client.db.backup_create("bad name")


def test_db_repair_passes_on_a_healthy_database(client: vethuq.Vethuq):
    client.db.integrity_check()

    assert client.db.repair().ok


def test_db_reset_removes_the_database(client: vethuq.Vethuq):
    client.db.integrity_check()

    assert client.db.reset() is not None


def test_backup_settings_defaults_and_roundtrip(client: vethuq.Vethuq):
    backup = client.settings.db.backup
    assert backup.get() == "enable"
    assert backup.get_interval_minutes() == 24 * 60
    assert backup.get_retention_days() == 7

    backup.set("disable")
    backup.set_interval_minutes(60)
    backup.set_retention_days(14)

    assert backup.get() == "disable"
    assert backup.get_interval_minutes() == 60
    assert backup.get_retention_days() == 14
    with pytest.raises(vethuq.InvalidSettingValueError):
        backup.set("auto")
