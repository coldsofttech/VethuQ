"""The same input must give the same stored output, whatever the scan order or worker count."""

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
    "d.png": b"content d",
    "a.png": b"content a",
    "c.png": b"content c",
    "b.png": b"content b",
    "sub/e.png": b"content e",
    "sub/a.png": b"content a2",
}
DUPLICATES = {"copy1.png": b"same bytes", "copy2.png": b"same bytes", "copy3.png": b"same bytes"}


class Determinism:
    @staticmethod
    def make_folder(root: Path, files: dict[str, bytes], order: list[str]) -> Path:
        root.mkdir(parents=True)
        for name in order:
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(files[name])
        return root

    @staticmethod
    def run(storage: Storage, conn: sqlite3.Connection, folder: Path, workers: int) -> list[tuple]:
        """Index `folder`, returning its stored state with ids/timestamps normalised away."""
        source = Sources.add(storage, folder)
        Quick.run_batch(storage, [source], workers=workers)
        rows = conn.execute(
            "SELECT di.file_path, di.status, di.sha256, di.document_id, ip.ocr_text "
            "FROM document_index di LEFT JOIN image_pages ip ON ip.document_id = di.document_id "
            "ORDER BY di.file_path"
        ).fetchall()
        return [
            (
                Path(r["file_path"]).relative_to(folder).as_posix(),
                r["status"],
                r["sha256"],
                r["ocr_text"],
            )
            for r in rows
        ]

    @staticmethod
    def wipe(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in ("image_pages", "document_phases", "document_index", "documents", "sources"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def link_groups(conn: sqlite3.Connection, folder: Path) -> list[list[str]]:
        """Which files share a logical document, as sorted groups of relative paths."""
        groups: dict[int, list[str]] = {}
        for r in conn.execute("SELECT file_path, document_id FROM document_index"):
            groups.setdefault(r["document_id"], []).append(
                Path(r["file_path"]).relative_to(folder).as_posix()
            )
        return sorted(sorted(g) for g in groups.values())


@pytest.fixture
def fake_ocr():
    engine = PaddleStub()
    engine.predict.return_value = [{"rec_texts": ["hello world"], "rec_scores": [0.95]}]
    with patch("vethuq_core.ocr.engines.Engines.get", return_value=engine):
        yield engine


@pytest.fixture(autouse=True)
def fixed_workers(storage: Storage):
    IndexSettings.set_thread_workers(storage, "1")


class TestDeterminism:
    def test_scan_order_does_not_change_the_stored_output(
        self, conn, storage: Storage, tmp_path: Path, fake_ocr
    ):
        names = list(FILES)
        forward = Determinism.make_folder(tmp_path / "fwd", FILES, names)
        first = Determinism.run(storage, conn, forward, workers=1)

        Determinism.wipe(conn)

        backward = Determinism.make_folder(tmp_path / "bwd", FILES, names[::-1])
        second = Determinism.run(storage, conn, backward, workers=1)

        assert first == second

    @pytest.mark.parametrize("workers", [2, 4, 8])
    def test_worker_count_does_not_change_the_stored_output(
        self, conn, storage: Storage, tmp_path: Path, fake_ocr, workers: int
    ):
        names = list(FILES)
        sequential = Determinism.make_folder(tmp_path / "seq", FILES, names)
        expected = Determinism.run(storage, conn, sequential, workers=1)

        Determinism.wipe(conn)

        parallel = Determinism.make_folder(tmp_path / "par", FILES, names)
        assert Determinism.run(storage, conn, parallel, workers=workers) == expected

    @pytest.mark.parametrize("workers", [1, 2, 4])
    def test_identical_files_always_group_the_same_way(
        self, conn, storage: Storage, tmp_path: Path, fake_ocr, workers: int
    ):
        folder = Determinism.make_folder(tmp_path / "dups", DUPLICATES, list(DUPLICATES))

        Determinism.run(storage, conn, folder, workers=workers)

        assert Determinism.link_groups(conn, folder) == [["copy1.png", "copy2.png", "copy3.png"]]
        # the alphabetically first copy is the one that was actually OCR'd
        assert fake_ocr.predict.call_count == 1
