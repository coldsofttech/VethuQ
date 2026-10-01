import sqlite3
from unittest.mock import MagicMock, patch

from vethuq_core.ocr import Scheduler
from vethuq_core.settings import IndexSettings


class TestScheduler:
    def test_resolve_thread_workers_disabled_by_default(self, conn: sqlite3.Connection):
        assert Scheduler.resolve_workers(conn, {"pdf": 0, "image": 5}) == 0

    def test_resolve_thread_workers_fixed_value_capped_to_pending_count(
        self, conn: sqlite3.Connection
    ):
        IndexSettings.set_thread_workers(conn, "8")

        assert Scheduler.resolve_workers(conn, {"pdf": 0, "image": 3}) == 3

    def test_resolve_thread_workers_fixed_value_unaffected_by_zero_pending(
        self, conn: sqlite3.Connection
    ):
        IndexSettings.set_thread_workers(conn, "4")

        assert Scheduler.resolve_workers(conn, {"pdf": 0, "image": 0}) == 4

    @patch("vethuq_core.ocr.scheduler.psutil.virtual_memory")
    @patch("vethuq_core.ocr.scheduler.psutil.cpu_percent")
    @patch("vethuq_core.ocr.scheduler.psutil.cpu_count")
    def test_auto_worker_count_scales_down_when_cpu_busy(
        self, mock_cpu_count, mock_cpu_percent, mock_virtual_memory
    ):
        mock_cpu_count.return_value = 8
        mock_cpu_percent.return_value = 90.0
        mock_virtual_memory.return_value = MagicMock(percent=20.0, available=8 * 1024 * 1024 * 1024)

        assert Scheduler.auto_worker_count({"pdf": 0, "image": 10}, 10) == 1

    @patch("vethuq_core.ocr.scheduler.psutil.virtual_memory")
    @patch("vethuq_core.ocr.scheduler.psutil.cpu_percent")
    @patch("vethuq_core.ocr.scheduler.psutil.cpu_count")
    def test_auto_worker_count_scales_down_when_memory_scarce(
        self, mock_cpu_count, mock_cpu_percent, mock_virtual_memory
    ):
        mock_cpu_count.return_value = 8
        mock_cpu_percent.return_value = 10.0
        mock_virtual_memory.return_value = MagicMock(
            percent=20.0,
            available=500 * 1024 * 1024,  # under one engine's footprint
        )

        assert Scheduler.auto_worker_count({"pdf": 0, "image": 10}, 10) == 1

    @patch("vethuq_core.ocr.scheduler.psutil.virtual_memory")
    @patch("vethuq_core.ocr.scheduler.psutil.cpu_percent")
    @patch("vethuq_core.ocr.scheduler.psutil.cpu_count")
    def test_auto_worker_count_capped_at_pending_file_count(
        self, mock_cpu_count, mock_cpu_percent, mock_virtual_memory
    ):
        mock_cpu_count.return_value = 16
        mock_cpu_percent.return_value = 5.0
        mock_virtual_memory.return_value = MagicMock(
            percent=10.0, available=32 * 1024 * 1024 * 1024
        )

        assert Scheduler.auto_worker_count({"pdf": 0, "image": 2}, 2) == 2
