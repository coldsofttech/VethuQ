import sqlite3
import sys
from unittest.mock import MagicMock, patch

from vethuq_core.ocr import Engine
from vethuq_core.settings import GpuSettings


class TestEngine:
    def test_resolve_device_defaults_to_cpu(self, conn: sqlite3.Connection):
        assert Engine.resolve_device(conn) == "cpu"

    def test_resolve_device_uses_gpu_when_enabled_and_available(self, conn: sqlite3.Connection):
        mock_paddle = MagicMock()
        mock_paddle.device.is_compiled_with_cuda.return_value = True
        mock_paddle.device.cuda.device_count.return_value = 1
        GpuSettings.set_enabled(conn, True)

        with patch.dict(sys.modules, {"paddle": mock_paddle}):
            assert Engine.resolve_device(conn) == "gpu"

    def test_resolve_device_falls_back_to_cpu_when_enabled_but_unsupported(
        self,
        conn: sqlite3.Connection,
    ):
        mock_paddle = MagicMock()
        mock_paddle.device.is_compiled_with_cuda.return_value = False
        GpuSettings.set_enabled(conn, True)

        with patch.dict(sys.modules, {"paddle": mock_paddle}):
            assert Engine.resolve_device(conn) == "cpu"

    def test_get_engine_enables_angle_orientation_detection(self, conn: sqlite3.Connection):
        mock_paddleocr_module = MagicMock()

        if hasattr(Engine._local, "engine"):
            del Engine._local.engine
        try:
            with patch.dict(sys.modules, {"paddleocr": mock_paddleocr_module}):
                Engine.get(conn)
        finally:
            if hasattr(Engine._local, "engine"):
                del Engine._local.engine

        _, kwargs = mock_paddleocr_module.PaddleOCR.call_args
        assert kwargs["use_doc_orientation_classify"] is True
        assert kwargs["use_textline_orientation"] is True
