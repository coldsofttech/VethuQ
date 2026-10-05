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
    # The installer's saved file/engine selection lives here too; keep the machine's out of tests.
    monkeypatch.setattr(
        "vethuq._core.paths.Paths.platform_data_root", staticmethod(lambda: data_dir)
    )
    monkeypatch.setattr(
        "vethuq._core.paths.Paths.location_file",
        staticmethod(lambda: data_dir / "config" / "location.json"),
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
    assert client.settings.search.normalize.leetspeak.get() == "auto"
    assert client.settings.search.normalize.case.get() == "auto"
    assert client.settings.search.normalize.unicode.get() == "auto"
    assert client.settings.search.noise_fuzzy.noise.get() == "low"
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


def test_index_rebuild_search_rebuilds_every_table_and_reports_progress(client: vethuq.Vethuq):
    seen = []

    result = client.index.rebuild_search(on_progress=lambda *args: seen.append(args))

    assert isinstance(result, vethuq.SearchIndexRebuildResult)
    assert result.ok is True
    assert len(result.rebuilt) >= 8
    assert [position for _, position, _ in seen] == list(range(1, len(result.rebuilt) + 1))


def test_settings_gpu_enable_and_disable(client: vethuq.Vethuq):
    client.settings.gpu.enable()
    assert client.settings.gpu.is_enabled() is True

    client.settings.gpu.disable()
    assert client.settings.gpu.is_enabled() is False


def test_settings_reset_restores_the_defaults(client: vethuq.Vethuq):
    search = client.settings.search
    search.snippet.set(5)
    search.export_format.set("html")
    search.engine.set("exact")
    search.fuzzy.threshold.set("strict")
    search.proximity.distance.set("tight")
    search.normalize.case.set("match")
    search.normalize.leetspeak.set("extended")
    search.normalize.unicode.set("full")
    search.noise_fuzzy.noise.set("high")
    client.settings.gpu.enable()
    client.settings.ocr.retry.set(9)
    client.settings.ocr.engine.set("deep")
    client.settings.index.removed_retention.set(5)
    client.settings.index.stability_check.set(0)
    client.settings.index.thread_workers.set("4")
    client.settings.index.stale_lock.set("disable")
    client.settings.db.integrity_check.set("disable")
    client.settings.db.integrity_check.set_interval_minutes(5)
    client.settings.db.backup.set("disable")
    client.settings.db.backup.set_interval_minutes(5)
    client.settings.db.backup.set_retention_days(30)
    client.settings.logs.level.set("debug")
    client.settings.logs.retention.set(30)

    for setting in (
        search.snippet,
        search.export_format,
        search.engine,
        search.fuzzy.threshold,
        search.proximity.distance,
        search.normalize.case,
        search.normalize.leetspeak,
        search.normalize.unicode,
        search.noise_fuzzy.noise,
        client.settings.gpu,
        client.settings.ocr.retry,
        client.settings.ocr.engine,
        client.settings.index.removed_retention,
        client.settings.index.stability_check,
        client.settings.index.thread_workers,
        client.settings.index.stale_lock,
        client.settings.db.integrity_check,
        client.settings.db.backup,
        client.settings.logs.level,
        client.settings.logs.retention,
    ):
        setting.reset()
    client.settings.db.integrity_check.reset_interval_minutes()
    client.settings.db.backup.reset_interval_minutes()
    client.settings.db.backup.reset_retention_days()

    assert search.snippet.get() == 80
    assert search.export_format.get() == "json"
    assert search.engine.get() == "all"
    assert search.normalize.case.get() == "auto"
    assert search.normalize.leetspeak.get() == "auto"
    assert search.normalize.unicode.get() == "auto"
    assert search.noise_fuzzy.noise.get() == "low"
    assert client.settings.gpu.is_enabled() is False
    assert client.settings.ocr.retry.get() == 3
    assert client.settings.ocr.engine.get() == "quick"
    assert client.settings.index.thread_workers.get() == "0"
    assert client.settings.index.stale_lock.get() == "auto"
    assert client.settings.db.integrity_check.get() == "auto"
    assert client.settings.db.integrity_check.get_interval_minutes() == 1440
    assert client.settings.db.backup.get() == "enable"
    assert client.settings.db.backup.get_interval_minutes() == 1440
    assert client.settings.db.backup.get_retention_days() == 7
    assert client.settings.logs.level.get() == "info"
    assert client.settings.logs.retention.get() == 15


def test_settings_values_round_trip(client: vethuq.Vethuq):
    client.settings.search.snippet.set(120)
    client.settings.search.export_format.set("html")
    client.settings.search.engine.set("full-text")
    client.settings.search.normalize.leetspeak.set("extended")
    client.settings.search.normalize.case.set("match")
    client.settings.search.normalize.unicode.set("full")
    client.settings.search.noise_fuzzy.noise.set("high")
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
    assert client.settings.search.normalize.leetspeak.get() == "extended"
    assert client.settings.search.normalize.case.get() == "match"
    assert client.settings.search.normalize.unicode.get() == "full"
    assert client.settings.search.noise_fuzzy.noise.get() == "high"
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
        lambda s: s.search.normalize.leetspeak.set("insane"),
        lambda s: s.search.normalize.case.set("sometimes"),
        lambda s: s.search.normalize.unicode.set("nfd"),
        lambda s: s.search.noise_fuzzy.noise.set("loud"),
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
        "leetspeak",
        "case",
        "unicode",
        "noise_level",
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


def test_search_like_reads_look_alikes_when_asked(indexed_client: vethuq.Vethuq):
    assert indexed_client.search.run("1nv01c3", engine="like") == []

    matches = indexed_client.search.run("1nv01c3", engine="like", leet_level="basic")

    assert [m.matched for m in matches] == ["Invoice", "INVOICE"]
    assert {m.engine for m in matches} == {"like"}
    assert vethuq.SEARCH_LEETSPEAK_LEVELS == ("basic", "standard", "extended")
    assert vethuq.SEARCH_LEETSPEAK_VALUES == ("auto", "off", "basic", "standard", "extended")
    assert vethuq.SEARCH_CASE_VALUES == ("auto", "ignore", "match")
    assert "leetspeak" not in vethuq.SEARCH_ENGINES
    assert "leetspeak" not in vethuq.ENGINE_TIERS
    assert set(vethuq.ENGINE_MODIFIERS) == {"accents", "look-alike"}


def test_search_leetspeak_can_be_chosen_per_search_or_stored(indexed_client: vethuq.Vethuq):
    assert indexed_client.search.run("inv0!c3", engine="like", leet_level="basic") == []
    standard = indexed_client.search.run("inv0!c3", engine="like", leet_level="standard")
    assert [m.matched for m in standard] == ["Invoice", "INVOICE"]  # ! is i from standard on
    assert indexed_client.search.run_pages("1nv01c3", leet_level="standard")
    assert indexed_client.settings.search.normalize.leetspeak.get() == "auto"

    indexed_client.settings.search.normalize.leetspeak.set("basic")
    assert indexed_client.search.run("1nv01c3", engine="like")
    assert indexed_client.search.run("1nv01c3", engine="like", leet_level="off") == []


def test_search_noise_fuzzy_finds_text_hidden_by_noise_look_alikes_and_typos(
    indexed_client: vethuq.Vethuq,
):
    matches = indexed_client.search.run("1nv01c3", engine="noise-fuzzy")
    assert [m.matched for m in matches] == ["Invoice", "INVOICE"]
    assert {m.engine for m in matches} == {"noise-fuzzy"}

    assert indexed_client.search.run("inv0ice", engine="noise-fuzzy")
    assert vethuq.SEARCH_NOISE_LEVELS == ("low", "medium", "high")
    assert "noise-fuzzy" in vethuq.SEARCH_ENGINES
    assert "noise-fuzzy" in vethuq.ENGINE_TIERS
    assert vethuq.ENGINE_BADGES["noise-fuzzy"] == "Obscured"
    assert vethuq.ENGINE_TIERS[-1] == "noise-fuzzy"


def test_search_noise_level_can_be_chosen_per_search(indexed_client: vethuq.Vethuq):
    # "In~voice" is one stray character; "I n v o i c e" is six.
    indexed_client.search.run("invoice", engine="noise-fuzzy", noise="low")
    assert indexed_client.search.run("In v o i c e", engine="noise-fuzzy") != []  # query noise
    matches_low = indexed_client.search.run_pages("invoice", noise="low")
    matches_high = indexed_client.search.run_pages("invoice", noise="high")
    assert len(matches_high) >= len(matches_low)
    assert indexed_client.settings.search.noise_fuzzy.noise.get() == "low"


def test_search_noise_fuzzy_honours_threshold_level_and_case(indexed_client: vethuq.Vethuq):
    assert indexed_client.search.run("INVOISE", engine="noise-fuzzy", threshold="loose")
    assert indexed_client.search.run("invoice", engine="noise-fuzzy", case_sensitive=True) != []
    assert (
        indexed_client.search.run(
            "invoice", engine="noise-fuzzy", case_sensitive=True, threshold="strict"
        )
        == []
    )  # 'Invoice' and 'INVOICE' each differ in case
    assert indexed_client.search.run("inv0!c3", engine="noise-fuzzy", leet_level="standard")


def test_search_like_look_alikes_honour_case_sensitive(indexed_client: vethuq.Vethuq):
    # A look-alike stands for the lower-case letter, so only that case matches it.
    matches = indexed_client.search.run(
        "Inv01c3", engine="like", leet_level="basic", case_sensitive=True
    )

    assert [m.matched for m in matches] == ["Invoice"]


def test_search_unicode_folds_accents_for_the_engines_that_take_it(indexed_client: vethuq.Vethuq):
    assert vethuq.SEARCH_UNICODE_LEVELS == ("off", "basic", "full")
    assert vethuq.SEARCH_UNICODE_VALUES == ("auto", "off", "basic", "full")
    # "Total due on this Invoice is 40 USD": an accent on a letter of it, as typed in the query.
    assert indexed_client.search.run("Invoicé", engine="like") == []

    matches = indexed_client.search.run("Invoicé", engine="like", unicode="full")

    assert [m.matched for m in matches] == ["Invoice", "INVOICE"]
    assert indexed_client.search.run("Invoicé", engine="fuzzy", unicode="full")
    assert indexed_client.search.run("Invoicé", engine="noise-fuzzy", unicode="full")
    assert indexed_client.search.run_pages("Invoicé", unicode="full")


def test_search_unicode_stored_setting_applies_except_to_exact(indexed_client: vethuq.Vethuq):
    indexed_client.settings.search.normalize.unicode.set("full")

    assert indexed_client.search.run("Invoicé", engine="like")
    assert indexed_client.search.run("Invoicé", engine="exact") == []
    assert indexed_client.search.run("Invoicé", engine="exact", unicode="full")


def test_search_case_setting_applies_to_like(indexed_client: vethuq.Vethuq):
    indexed_client.settings.search.normalize.case.set("match")

    assert indexed_client.settings.search.normalize.case.get() == "match"
    assert [m.matched for m in indexed_client.search.run("INVOICE", engine="like")] == ["INVOICE"]

    indexed_client.settings.search.normalize.case.set("ignore")
    assert indexed_client.settings.search.normalize.case.get() == "ignore"


def test_search_uses_the_configured_engine(indexed_client: vethuq.Vethuq):
    indexed_client.settings.search.engine.set("exact")

    assert indexed_client.search.run("invoice") == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"engine": "nope"},
        {"engine": "full-text", "case_sensitive": True},
        {"engine": "exact", "case_sensitive": False},
        {"engine": "leetspeak"},
        {"engine": "fuzzy", "leet_level": "basic"},
        {"engine": "like", "leet_level": "insane"},
        {"engine": "like", "threshold": 0.8},
        {"engine": "full-text", "unicode": "full"},
        {"engine": "lexical", "unicode": "full"},
        {"engine": "like", "unicode": "nfd"},
        {"engine": "like", "noise": "low"},
        {"engine": "noise-fuzzy", "noise": "loud"},
        {"engine": "noise-fuzzy", "distance": 3},
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


def test_sources_purge_deletes_removed_source_and_refuses_active(
    client: vethuq.Vethuq, docs_folder: Path
):
    source = client.sources.add(docs_folder)

    with pytest.raises(vethuq.SourceNotRemovedError):
        client.sources.purge(source.id)

    client.sources.remove(source.id)
    result = client.sources.purge(source.id)

    assert result.path == source.path
    assert client.sources.list(include_inactive=True) == []


def test_version_reports_install_details(client: vethuq.Vethuq) -> None:
    info = client.version

    assert isinstance(info, vethuq.VersionDetails)
    assert info.python and info.platform
    assert info.db_schema > 0


class TestStartupErrors:
    def test_startup_errors_are_exported_with_distinct_exit_codes(self):
        names = [
            "InvalidConfigError",
            "DataFolderNotWritableError",
            "CorruptDatabaseError",
            "OcrModelMissingError",
            "SchemaVersionError",
            "StaleLockError",
        ]
        classes = [getattr(vethuq, name) for name in names]

        assert all(issubclass(cls, vethuq.StartupError) for cls in classes)
        assert len({cls.exit_code for cls in classes}) == len(classes)
        assert all(name in vethuq.__all__ for name in names + ["StartupError"])


# --- file types --------------------------------------------------------------------------------


def test_file_types_lists_installed_types(client: vethuq.Vethuq):
    listed = client.file_types.list()

    assert "pdf" in {t.id for t in listed}
    assert all(isinstance(t, vethuq.FileTypeInfo) and t.installed for t in listed)
    assert all(t.install_hint is None for t in listed)


def test_file_types_include_missing_lists_every_type(
    client: vethuq.Vethuq, monkeypatch: pytest.MonkeyPatch
):
    from vethuq._core.filetypes import FileType

    real = FileType.is_installed
    monkeypatch.setattr(
        FileType, "is_installed", lambda self: False if self.id == "png" else real(self)
    )

    assert "png" not in {t.id for t in client.file_types.list()}
    everything = {t.id: t for t in client.file_types.list(include_missing=True)}
    assert {"pdf", "png", "jpg"} <= set(everything)
    assert everything["png"].installed is False
    assert everything["png"].install_hint == "pip install vethuq[type-png]"


def test_search_can_be_limited_to_the_language_a_page_was_read_in(indexed_client: vethuq.Vethuq):
    # The seeded pages have no language recorded, which means English.
    assert indexed_client.search.run("Invoice", engine="exact", languages="en")
    assert indexed_client.search.run("Invoice", engine="exact", languages="te") == []
    assert indexed_client.search.run_pages("invoice", languages="te") == []
    assert indexed_client.search.run("Invoice", engine="exact", languages="auto")


def test_search_rejects_an_unknown_language(indexed_client: vethuq.Vethuq):
    with pytest.raises(vethuq.SearchLanguageError):
        indexed_client.search.run("invoice", languages="xx")


def test_statistics_can_be_limited_to_a_language(client: vethuq.Vethuq):
    assert client.stats.processing(language="te") == []
    assert client.stats.confidence(language="te") == []
