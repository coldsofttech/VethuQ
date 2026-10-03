"""Identical content resolves to one document identity, and the same file is always its original."""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import PaddleStub
from vethuq_core.ocr import Quick
from vethuq_core.settings import IndexSettings
from vethuq_core.sources import Sources
from vethuq_core.storage import Storage

FILES = {
    "a.png": b"alpha",
    "b.png": b"same bytes",
    "c.png": b"same bytes",
    "d.png": b"beta",
    "sub/e.png": b"same bytes",
}


class Identity:
    @staticmethod
    def make_folder(root: Path, order: list[str]) -> Path:
        root.mkdir(parents=True)
        for name in order:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(FILES[name])
        return root

    @staticmethod
    def groups(conn: sqlite3.Connection, folder: Path) -> list[list[str]]:
        """Files sharing a logical document, as sorted groups of relative paths."""
        by_document: dict[int, list[str]] = {}
        for r in conn.execute("SELECT file_path, document_id FROM document_index"):
            by_document.setdefault(r["document_id"], []).append(
                Path(r["file_path"]).relative_to(folder).as_posix()
            )
        return sorted(sorted(g) for g in by_document.values())

    @staticmethod
    def originals(conn: sqlite3.Connection, folder: Path) -> set[str]:
        """The original of each group: the earliest-indexed file (lowest row id)."""
        rows = conn.execute(
            "SELECT file_path FROM document_index WHERE id IN "
            "(SELECT MIN(id) FROM document_index GROUP BY document_id)"
        ).fetchall()
        return {Path(r["file_path"]).relative_to(folder).as_posix() for r in rows}

    @staticmethod
    def document_ids(conn: sqlite3.Connection) -> dict[str, int]:
        return {
            r["file_path"]: r["document_id"] for r in conn.execute("SELECT * FROM document_index")
        }


@pytest.fixture
def fake_ocr():
    engine = PaddleStub()
    engine.predict.return_value = [{"rec_texts": ["hello"], "rec_scores": [0.95]}]
    with patch("vethuq_core.ocr.engines.Engines.get", return_value=engine):
        yield engine


@pytest.fixture(autouse=True)
def fixed_workers(storage: Storage):
    IndexSettings.set_thread_workers(storage, "1")


class TestDocumentIdentity:
    def test_reindexing_keeps_every_document_identity(
        self, conn, storage: Storage, tmp_path: Path, fake_ocr
    ):
        folder = Identity.make_folder(tmp_path / "src", list(FILES))
        source = Sources.add(storage, folder)
        Quick.run_batch(storage, [source], workers=1)
        before = Identity.document_ids(conn)

        Quick.run_batch(storage, [source], workers=1)

        assert Identity.document_ids(conn) == before

    @pytest.mark.parametrize("workers", [1, 4])
    def test_readding_a_source_resolves_to_the_same_groups(
        self, conn, storage: Storage, tmp_path: Path, fake_ocr, workers: int
    ):
        folder = Identity.make_folder(tmp_path / "src", list(FILES))
        source = Sources.add(storage, folder)
        Quick.run_batch(storage, [source], workers=workers)
        groups, originals = Identity.groups(conn, folder), Identity.originals(conn, folder)

        Sources.remove(storage, source.id)
        Quick.run_batch(storage, [Sources.add(storage, folder)], workers=workers)

        assert Identity.groups(conn, folder) == groups
        assert Identity.originals(conn, folder) == originals

    def test_creation_order_does_not_change_the_groups(
        self, conn, storage: Storage, tmp_path: Path, fake_ocr
    ):
        names = list(FILES)
        forward = Identity.make_folder(tmp_path / "fwd", names)
        Quick.run_batch(storage, [Sources.add(storage, forward)], workers=1)
        expected = Identity.groups(conn, forward)
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in ("image_pages", "document_phases", "document_index", "documents", "sources"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

        backward = Identity.make_folder(tmp_path / "bwd", names[::-1])
        Quick.run_batch(storage, [Sources.add(storage, backward)], workers=1)

        assert Identity.groups(conn, backward) == expected

    def test_identical_content_across_sources_shares_one_document(
        self, conn, storage: Storage, tmp_path: Path, fake_ocr
    ):
        one = Identity.make_folder(tmp_path / "one", ["b.png"])
        two = Identity.make_folder(tmp_path / "two", ["c.png"])

        Quick.run_batch(storage, [Sources.add(storage, one), Sources.add(storage, two)], workers=2)

        assert len(set(Identity.document_ids(conn).values())) == 1
        assert fake_ocr.predict.call_count == 1


class TestDuplicateOriginal:
    @pytest.mark.parametrize("workers", [1, 2, 4, 8])
    def test_original_is_the_first_file_in_path_order(
        self, conn, storage: Storage, tmp_path: Path, fake_ocr, workers: int
    ):
        # created in reverse so neither creation order nor name order is the accident
        folder = Identity.make_folder(tmp_path / "src", list(FILES)[::-1])
        Quick.run_batch(storage, [Sources.add(storage, folder)], workers=workers)

        assert Identity.originals(conn, folder) == {"a.png", "b.png", "d.png"}
        assert fake_ocr.predict.call_count == 3  # one OCR pass per distinct content
