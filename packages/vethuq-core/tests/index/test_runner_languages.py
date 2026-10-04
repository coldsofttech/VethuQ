import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from vethuq_core.db import Db
from vethuq_core.errors import LanguageUnavailableError, OcrModelMissingError
from vethuq_core.index import IndexRunner
from vethuq_core.index import runner as index_runner
from vethuq_core.ocr import Ocr, Pending
from vethuq_core.paths import Paths
from vethuq_core.sources import Sources

MODELS = ["PP-OCRv5_server_det", "PP-LCNet_x1_0_doc_ori", "PP-LCNet_x1_0_textline_ori"]
TE_REC = "te_PP-OCRv5_mobile_rec"


class _FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid


@pytest.fixture
def db_path(tmp_path) -> Path:
    path = tmp_path / "vethuq.db"
    Db.connect(path).close()
    return path


@pytest.fixture
def conn(db_path):
    connection = Db.connect(db_path)
    yield connection
    connection.close()


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PADDLE_PDX_CACHE_HOME", str(tmp_path / "paddlex"))
    return tmp_path / "paddlex" / "official_models"


@pytest.fixture
def launched(monkeypatch):
    """Records the argv of every worker the runner starts."""
    argvs: list[list[str]] = []

    def popen(argv, **kwargs):
        argvs.append(argv)
        return _FakeProcess(4321)

    monkeypatch.setattr(index_runner.subprocess, "Popen", popen)
    return argvs


def _download_models(cache: Path, *names: str) -> None:
    for name in names:
        (cache / name).mkdir(parents=True, exist_ok=True)
        (cache / name / "inference.pdiparams").write_bytes(b"x")


def _only_english() -> None:
    (Paths.default_data_root() / "languages.json").write_text(
        json.dumps({"enabled": ["en"]}), encoding="utf-8"
    )


class TestWorkerCommand:
    def test_the_command_is_unchanged_without_languages(self, db_path):
        command = IndexRunner._worker_command(db_path, "3", False)

        assert command == [
            sys.executable,
            "-m",
            "vethuq_core.index.runner",
            str(db_path),
            "3",
            "run",
        ]

    def test_languages_follow_the_mode(self, db_path):
        command = IndexRunner._worker_command(db_path, None, True, "te")

        assert command[-3:] == ["", "restart", "te"]

    def test_start_run_hands_the_languages_to_the_worker(self, db_path, launched, cache):
        _download_models(cache, *MODELS, TE_REC)

        IndexRunner.start_run(None, db_path=db_path, languages="te")

        assert launched[0][-1] == "te"

    def test_start_run_without_languages_adds_nothing(self, db_path, launched, cache):
        IndexRunner.start_run(None, db_path=db_path)

        assert launched[0][-1] == "run"


class TestLanguageChecks:
    def test_a_language_that_is_not_installed_stops_the_run_before_it_starts(
        self, db_path, launched
    ):
        _only_english()

        with pytest.raises(LanguageUnavailableError) as raised:
            IndexRunner.start_run(None, db_path=db_path, languages="te")

        assert "pip install vethuq[lang-te]" in str(raised.value)
        assert launched == []
        assert not IndexRunner._lock_path(db_path).exists()

    def test_an_unknown_language_stops_the_run(self, db_path, launched):
        with pytest.raises(LanguageUnavailableError, match="Unknown language 'xx'"):
            IndexRunner.start_run(None, db_path=db_path, languages="xx")

        assert launched == []

    def test_telugu_for_every_file_needs_its_models_downloaded(self, db_path, launched, cache):
        with pytest.raises(OcrModelMissingError) as raised:
            IndexRunner.start_run(None, db_path=db_path, languages="te")

        assert "Telugu OCR models are not downloaded (4 missing)" in raised.value.message
        assert raised.value.hint == "Run: vethuq ocr models download --lang te"
        assert launched == []

    def test_only_what_is_missing_is_counted(self, db_path, launched, cache):
        _download_models(cache, *MODELS)

        with pytest.raises(OcrModelMissingError, match=r"\(1 missing\)"):
            IndexRunner.start_run(None, db_path=db_path, languages="te")

    def test_downloaded_models_let_the_run_start(self, db_path, launched, cache):
        _download_models(cache, *MODELS, TE_REC)

        assert IndexRunner.start_run(None, db_path=db_path, languages="te") == 4321

    def test_the_source_languages_are_checked_too(self, db_path, conn, launched, cache, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        Sources.add(Storage_for(conn), folder, languages="te")

        with pytest.raises(OcrModelMissingError):
            IndexRunner.start_run(None, db_path=db_path)

    def test_with_several_candidates_missing_models_do_not_stop_the_run(
        self, db_path, launched, cache
    ):
        # `auto` (the default) is English and Telugu here; Telugu is only needed for files
        # English doubts, so English files must not be held up by it.
        assert IndexRunner.start_run(None, db_path=db_path) == 4321
        assert IndexRunner.start_run(None, db_path=db_path, force=True, languages="en,te") == 4321

    def test_english_never_blocks_a_run_on_its_models(self, db_path, launched, cache):
        _only_english()

        assert IndexRunner.start_run(None, db_path=db_path, languages="en") == 4321

    def test_a_target_is_checked_only_for_its_own_source(
        self, db_path, conn, launched, cache, tmp_path
    ):
        storage = Storage_for(conn)
        english = tmp_path / "english"
        telugu = tmp_path / "telugu"
        english.mkdir()
        telugu.mkdir()
        english_source = Sources.add(storage, english, languages="en")
        Sources.add(storage, telugu, languages="te")

        assert IndexRunner.start_run(str(english_source.id), db_path=db_path) == 4321


class TestMain:
    def test_the_worker_reads_the_languages_argument(self, db_path, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            IndexRunner,
            "_run_worker",
            staticmethod(lambda path, target, **kwargs: seen.update(kwargs, target=target)),
        )
        monkeypatch.setattr(sys, "argv", ["worker", str(db_path), "", "restart", "en,te"])

        IndexRunner.main()

        assert seen == {"target": None, "restart": True, "languages": "en,te"}

    def test_no_languages_argument_means_none(self, db_path, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            IndexRunner,
            "_run_worker",
            staticmethod(lambda path, target, **kwargs: seen.update(kwargs)),
        )
        monkeypatch.setattr(sys, "argv", ["worker", str(db_path), "3", "run"])

        IndexRunner.main()

        assert seen == {"restart": False, "languages": None}

    def test_the_worker_hands_them_to_the_phased_run(self, db_path, conn, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        Sources.add(Storage_for(conn), folder)
        conn.close()
        calls = []

        with (
            patch.object(Pending, "file_count", return_value=0),
            patch.object(Ocr, "run_phased", side_effect=lambda *a, **kw: calls.append(kw) or []),
        ):
            IndexRunner._run_worker(db_path, None, languages="te")

        assert calls[0]["languages"] == "te"


class TestRecovery:
    def test_interrupted_language_passes_go_back_in_the_queue(
        self, db_path, conn, launched, monkeypatch
    ):
        conn.executescript(
            """
            INSERT INTO sources (id, path, source_type, status, added_at)
                VALUES (1, '/a', 'folder', 'indexed', '2024-01-01');
            INSERT INTO documents (created_at) VALUES ('2024-01-01');
            INSERT INTO document_index (id, source_id, document_id, file_path, file_type, status)
                VALUES (1, 1, 1, '/a/x.png', 'image', 'indexed');
            INSERT INTO document_languages (document_id, language, position, status, started_at)
                VALUES (1, 'te', 1, 'processing', '2024-01-01');
            """
        )
        conn.commit()
        monkeypatch.setattr(IndexRunner, "_is_pid_running", lambda pid: False)
        IndexRunner._atomic_write(IndexRunner._lock_path(db_path), "999")
        recovered: list[str] = []

        IndexRunner.start_run(None, db_path=db_path, on_recovery=recovered.extend)

        row = conn.execute("SELECT status, started_at FROM document_languages").fetchone()
        assert (row["status"], row["started_at"]) == ("pending", None)
        assert any("Re-queued 1 language pass" in action for action in recovered)


def Storage_for(conn):
    from vethuq_core.storage.sqlite import SqliteStorage

    return SqliteStorage(conn)
