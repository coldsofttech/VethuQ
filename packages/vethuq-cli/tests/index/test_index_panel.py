from datetime import UTC, datetime

import vethuq_core.db as db_module
from vethuq_cli.index.panel import IndexPanel, StatePanel
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


class TestFriendlyTime:
    NOW = datetime(2026, 10, 3, 15, 0).astimezone()

    @staticmethod
    def _iso(year, month, day, hour=13, minute=40) -> str:
        return datetime(year, month, day, hour, minute).astimezone().isoformat()

    def test_today_and_yesterday_are_named(self):
        assert IndexPanel.friendly_time(self._iso(2026, 10, 3), self.NOW) == "Today, 13:40"
        assert (
            IndexPanel.friendly_time(self._iso(2026, 10, 2, 9, 5), self.NOW) == "Yesterday, 09:05"
        )

    def test_earlier_this_year_drops_the_year(self):
        assert IndexPanel.friendly_time(self._iso(2026, 3, 7), self.NOW) == "7 Mar, 13:40"

    def test_other_years_show_the_year(self):
        assert IndexPanel.friendly_time(self._iso(2025, 12, 25), self.NOW) == "25 Dec 2025, 13:40"

    def test_a_utc_timestamp_is_shown_in_local_time(self):
        utc = datetime(2026, 10, 3, 13, 40, 58, 849138, tzinfo=UTC)

        shown = IndexPanel.friendly_time(utc.isoformat(), self.NOW)

        assert shown == "Today, " + utc.astimezone().strftime("%H:%M")

    def test_a_value_that_is_not_a_timestamp_is_left_alone(self):
        assert IndexPanel.friendly_time("not a time") == "not a time"
