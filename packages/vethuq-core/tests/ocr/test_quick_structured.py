import sqlite3
from unittest.mock import patch

import pytest
from vethuq_core.ocr import Document, Quick
from vethuq_core.search import Search
from vethuq_core.source import Sources


def _doc(conn: sqlite3.Connection, path) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM document_index WHERE file_path = ?", (str(path.resolve()),)
    ).fetchone()


@pytest.fixture(autouse=True)
def _no_ocr_engine():
    # JSON/YAML must never touch the OCR engine - fail loudly if one is requested.
    with patch("vethuq_core.ocr.Engine.get", side_effect=AssertionError("engine used")):
        yield


class TestQuickStructured:
    def test_indexes_json_and_yaml_without_ocr(self, conn: sqlite3.Connection, tmp_path):
        (tmp_path / "app.json").write_text('{"service": {"name": "billing", "port": 9000}}')
        (tmp_path / "app.yaml").write_text("service:\n  name: shipping\n  replicas: 3\n")
        (tmp_path / "other.yml").write_text("owner: carol\n")
        source = Sources.add(conn, tmp_path)

        processed = Quick.run(conn, source)

        assert len(processed) == 3
        for name in ("app.json", "app.yaml", "other.yml"):
            doc = _doc(conn, tmp_path / name)
            assert doc["status"] == "indexed"
            assert doc["file_type"] == "structured"
            assert doc["file_size_bytes"] == (tmp_path / name).stat().st_size
        page = conn.execute(
            "SELECT * FROM structured_pages WHERE document_id = ?",
            (_doc(conn, tmp_path / "app.json")["id"],),
        ).fetchone()
        assert page["ocr_text"] == "service.name: billing\nservice.port: 9000"
        assert page["confidence"] == pytest.approx(1.0)

    def test_records_metrics_under_structured(self, conn: sqlite3.Connection, tmp_path):
        (tmp_path / "app.json").write_text('{"a": 1}')
        Quick.run(conn, Sources.add(conn, tmp_path))

        processing = conn.execute(
            "SELECT file_type, phase, document_count FROM processing_metrics"
        ).fetchall()
        confidence = conn.execute(
            "SELECT file_type, process_type, page_count, avg_confidence FROM confidence_metrics"
        ).fetchall()

        assert [tuple(r) for r in processing] == [("structured", 1, 1)]
        assert [tuple(r) for r in confidence] == [("structured", "native", 1, 1.0)]

    def test_search_finds_keys_and_values(self, conn: sqlite3.Connection, tmp_path):
        (tmp_path / "app.json").write_text('{"service": {"name": "billing"}}')
        (tmp_path / "app.yaml").write_text("database:\n  host: db.internal\n")
        Quick.run(conn, Sources.add(conn, tmp_path))

        by_value = Search.indexed_content(conn, "billing")
        by_key = Search.indexed_content(conn, "database.host")

        assert [m.file_name for m in by_value] == ["app.json"]
        assert by_value[0].page_number is None
        assert by_value[0].total_pages is None
        assert [m.file_name for m in by_key] == ["app.yaml"]
        assert by_key[0].matched == "database.host"

    def test_identical_files_are_linked_as_duplicates(self, conn: sqlite3.Connection, tmp_path):
        (tmp_path / "a.json").write_text('{"k": "uniquevalue"}')
        (tmp_path / "b.json").write_text('{"k": "uniquevalue"}')
        Quick.run(conn, Sources.add(conn, tmp_path))

        matches = Search.indexed_content(conn, "uniquevalue")

        assert sorted(m.file_name for m in matches) == ["a.json", "b.json"]
        assert conn.execute("SELECT COUNT(*) FROM structured_pages").fetchone()[0] == 1
        results = Document.get_results(conn, 1)
        assert {r.confidence for r in results} == {1.0}
        assert sum(r.duplicate_of_path is not None for r in results) == 1

    def test_modified_file_is_reindexed_and_old_text_is_gone(
        self, conn: sqlite3.Connection, tmp_path
    ):
        path = tmp_path / "app.yaml"
        path.write_text("stage: oldvalue\n")
        source = Sources.add(conn, tmp_path)
        Quick.run(conn, source)

        path.write_text("stage: newvalue-with-different-size\n")
        Quick.run(conn, source, only_new_files=True)

        assert Search.indexed_content(conn, "oldvalue") == []
        assert len(Search.indexed_content(conn, "newvalue")) == 1
        assert conn.execute("SELECT COUNT(*) FROM structured_pages").fetchone()[0] == 1

    def test_malformed_file_is_still_searchable(self, conn: sqlite3.Connection, tmp_path):
        (tmp_path / "broken.json").write_text('{"name": "halfwritten", ')
        Quick.run(conn, Sources.add(conn, tmp_path))

        assert _doc(conn, tmp_path / "broken.json")["status"] == "indexed"
        assert len(Search.indexed_content(conn, "halfwritten")) == 1

    def test_removing_a_source_purges_structured_pages(self, conn: sqlite3.Connection, tmp_path):
        (tmp_path / "app.json").write_text('{"a": "purgeme"}')
        source = Sources.add(conn, tmp_path)
        Quick.run(conn, source)
        assert Search.indexed_content(conn, "purgeme")

        Sources.remove(conn, source.id)

        assert Search.indexed_content(conn, "purgeme") == []

    def test_purging_an_expired_source_deletes_its_structured_pages(
        self, conn: sqlite3.Connection, tmp_path
    ):
        (tmp_path / "app.json").write_text('{"a": "purgeme"}')
        source = Sources.add(conn, tmp_path)
        Quick.run(conn, source)
        Sources.remove(conn, source.id)

        Sources.purge_expired_sources(conn, retention_minutes=-1)

        assert conn.execute("SELECT COUNT(*) FROM structured_pages").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM document_index").fetchone()[0] == 0

    def test_purging_the_original_hands_text_to_a_surviving_duplicate(
        self, conn: sqlite3.Connection, tmp_path
    ):
        (tmp_path / "a.json").write_text('{"k": "sharedtext"}')
        (tmp_path / "b.json").write_text('{"k": "sharedtext"}')
        Quick.run(conn, Sources.add(conn, tmp_path))
        original = conn.execute(
            "SELECT id, file_path FROM document_index "
            "WHERE id = (SELECT document_id FROM structured_pages)"
        ).fetchone()
        conn.execute(
            "UPDATE document_index "
            "SET status = 'removed', removed_at = '2000-01-01T00:00:00+00:00' WHERE id = ?",
            (original["id"],),
        )
        conn.commit()

        Sources.purge_expired_documents(conn, retention_minutes=-1)

        matches = Search.indexed_content(conn, "sharedtext")
        assert [m.file_path for m in matches] != [original["file_path"]]
        assert len(matches) == 1
