from datetime import UTC, datetime

import vethuq_core.db as db_module
from vethuq_cli.index.panel import StatePanel
from vethuq_core.index import runner as index_runner_module
from vethuq_core.sources import Sources
from vethuq_core.storage.sqlite import SqliteStorage


class TestStatePanel:
    def test_state_panel_shows_phase_and_a_bar_per_phase(self, use_temp_db, tmp_path):
        from rich.console import Console
        from vethuq_core.settings import OcrSettings

        db_path = use_temp_db()
        conn = db_module.Db.connect(db_path)
        folder = tmp_path / "src"
        folder.mkdir()
        source = Sources.add(SqliteStorage(conn), folder)
        for index, phase in enumerate((1, 2, 3), start=1):
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
                "VALUES (?, 'x', 0.9, ?, '0')",
                (index, phase),
            )
        conn.commit()
        OcrSettings.set_engine(SqliteStorage(conn), "deep")
        now = datetime.now(UTC).isoformat()
        state = index_runner_module.IndexState(
            run_id=1,
            pid=1,
            target=None,
            mode="run",
            status="running",
            total_files=3,
            processed_files=3,
            failed_files=0,
            thread_workers_setting="0",
            workers=1,
            current_files=[],
            started_at=now,
            updated_at=now,
            phase=2,
        )

        console = Console(width=100, record=True)
        console.print(StatePanel.build(SqliteStorage(conn), state, animated=False))
        text = console.export_text()
        conn.close()

        assert "moderate (2/3)" in text
        assert "Quick" in text and "3/3 (100%)" in text
        assert "Moderate" in text and "2/3 (67%)" in text
        assert "Deep" in text and "1/3 (33%)" in text
