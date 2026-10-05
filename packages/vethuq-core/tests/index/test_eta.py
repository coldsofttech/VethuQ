from datetime import UTC, datetime

from vethuq_core.index import Eta, IndexState
from vethuq_core.settings import OcrSettings
from vethuq_core.sources import Sources
from vethuq_core.storage import Storage


class TestEta:
    def test_phase_seconds_estimated_per_phase_from_each_phases_own_history(
        self, conn, storage: Storage, tmp_path
    ):
        folder = tmp_path / "src"
        folder.mkdir()
        source = Sources.add(storage, folder)
        conn.execute("UPDATE sources SET status = 'indexed' WHERE id = ?", (source.id,))
        # Two indexed image documents, both still waiting on moderate and deep.
        for index in (1, 2):
            document_id = conn.execute(
                "INSERT INTO documents (created_at) VALUES ('2026-01-01')"
            ).lastrowid
            conn.execute(
                "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
                "VALUES (?, ?, ?, 'image', 'indexed')",
                (source.id, document_id, str(folder / f"{index}.png")),
            )
            conn.execute(
                "INSERT INTO image_pages "
                "(document_id, ocr_text, confidence, ocr_phase, ocr_angles) "
                "VALUES (?, 'x', 0.9, 1, '0')",
                (index,),
            )
        # Quick is fast, moderate takes 30s a document; deep has no history yet.
        conn.execute(
            "INSERT INTO processing_metrics "
            "VALUES (1, 'image', 'png', 'small', 5, 1.0, 10, 5, 'now', 'en')"
        )
        conn.execute(
            "INSERT INTO processing_metrics "
            "VALUES (2, 'image', 'png', 'small', 5, 30.0, 10, 5, 'now', 'en')"
        )
        conn.commit()
        OcrSettings.set_engine(storage, "deep")
        now = datetime.now(UTC).isoformat()
        state = IndexState(
            run_id=1,
            pid=1,
            target=None,
            mode="run",
            status="running",
            total_files=2,
            processed_files=2,
            failed_files=0,
            thread_workers_setting="0",
            workers=1,
            current_files=[],
            started_at=now,
            updated_at=now,
        )

        by_phase = Eta.phase_seconds(storage, state)

        # 2 documents x 30s for moderate; nothing for quick (no files pending) or deep (no history).
        assert by_phase == {2: 60.0}
