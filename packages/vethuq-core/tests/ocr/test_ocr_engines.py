import ast
import sqlite3
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import vethuq_core.ocr as ocr_module
from vethuq_core.db import Db
from vethuq_core.ocr import Quick
from vethuq_core.ocr.engines import Engines, OcrEngine, OcrResult
from vethuq_core.ocr.engines.paddle import PaddleOcrEngine
from vethuq_core.settings import GpuSettings
from vethuq_core.source import Sources


class FakeEngine:
    """A minimal `OcrEngine` implementation, standing in for a future engine."""

    name = "fake-ocr 9.9"
    language = "de"

    def __init__(self) -> None:
        self.images: list[object] = []

    def recognize(self, image):
        self.images.append(image)
        return OcrResult(
            text="fake text",
            confidence=0.5,
            engine=self.name,
            language=self.language,
            image_width=10,
            image_height=20,
        )


@pytest.fixture
def isolated_registry():
    """Restore the registry and this thread's engine cache after a test swaps them."""
    saved = dict(Engines._factories)
    Engines._local.__dict__.pop("engines", None)
    yield
    Engines._factories.clear()
    Engines._factories.update(saved)
    Engines._local.__dict__.pop("engines", None)


def _paddle_engine(predict_result):
    fake_paddleocr = MagicMock()
    fake_paddleocr.PaddleOCR.return_value.predict.return_value = predict_result
    with (
        patch.dict(sys.modules, {"paddleocr": fake_paddleocr}),
        patch("vethuq_core.ocr.engines.paddle._package_version", return_value="3.0.0"),
    ):
        engine = PaddleOcrEngine()
    return engine, fake_paddleocr


class TestEngines:
    def test_fake_engine_satisfies_the_interface(self):
        engine: OcrEngine = FakeEngine()
        assert engine.recognize("x").text == "fake text"

    def test_orchestration_stores_whatever_engine_it_is_given(
        self, conn: sqlite3.Connection, tmp_path, isolated_registry
    ):
        engine = FakeEngine()
        Engines.register(Engines.DEFAULT, lambda use_gpu: engine)

        image_path = tmp_path / "scan.png"
        image_path.write_bytes(b"fake png bytes")
        source = Sources.add(conn, image_path)

        Quick.run(conn, source)

        assert engine.images == [str(image_path.resolve())]
        doc = conn.execute(
            "SELECT id, status FROM document_index WHERE file_path = ?",
            (str(image_path.resolve()),),
        ).fetchone()
        assert doc["status"] == "indexed"
        page = conn.execute(
            "SELECT * FROM image_pages WHERE document_id = ?", (doc["id"],)
        ).fetchone()
        assert page["ocr_text"] == "fake text"
        assert page["confidence"] == pytest.approx(0.5)
        assert page["ocr_engine"] == "fake-ocr 9.9"
        assert page["language"] == "de"
        assert page["image_width"] == 10
        assert page["image_height"] == 20

    def test_orchestration_never_imports_a_concrete_engine(self):
        ocr_dir = Path(ocr_module.__file__).parent
        imported = set()
        for path in ocr_dir.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)

        assert not {name for name in imported if "paddle" in name}

    def test_get_builds_once_per_thread(
        self, conn: sqlite3.Connection, tmp_path, isolated_registry
    ):
        built: list[FakeEngine] = []

        def factory(use_gpu: bool) -> FakeEngine:
            built.append(FakeEngine())
            return built[-1]

        Engines.register(Engines.DEFAULT, factory)

        db_path = tmp_path / "vethuq.db"
        main_thread_engine = Engines.get(conn)
        assert Engines.get(conn) is main_thread_engine

        other: list[object] = []

        def _in_other_thread() -> None:
            thread_conn = Db.connect(db_path)
            other.append(Engines.get(thread_conn))
            thread_conn.close()

        thread = threading.Thread(target=_in_other_thread)
        thread.start()
        thread.join()

        assert other[0] is not main_thread_engine
        assert len(built) == 2

    def test_get_passes_the_gpu_setting_to_the_factory(
        self, conn: sqlite3.Connection, isolated_registry
    ):
        flags: list[bool] = []

        def factory(use_gpu: bool) -> FakeEngine:
            flags.append(use_gpu)
            return FakeEngine()

        Engines.register(Engines.DEFAULT, factory)

        GpuSettings.set_enabled(conn, True)
        Engines.get(conn)

        assert flags == [True]

    def test_default_engine_is_paddleocr_and_loaded_lazily(
        self, conn: sqlite3.Connection, isolated_registry
    ):
        assert Engines.DEFAULT == "paddleocr"

        with patch("vethuq_core.ocr.engines.paddle.PaddleOcrEngine") as engine_cls:
            engine = Engines.get(conn)

        engine_cls.assert_called_once_with(use_gpu=False)
        assert engine is engine_cls.return_value


class TestPaddleOcrEngine:
    def test_reports_name_and_language(self):
        engine, fake_paddleocr = _paddle_engine([])

        assert engine.name == "paddleocr 3.0.0"
        assert engine.language == "en"
        assert fake_paddleocr.PaddleOCR.call_args.kwargs["lang"] == "en"
        assert fake_paddleocr.PaddleOCR.call_args.kwargs["device"] == "cpu"

    def test_enables_angle_orientation_detection(self):
        _, fake_paddleocr = _paddle_engine([])

        kwargs = fake_paddleocr.PaddleOCR.call_args.kwargs
        assert kwargs["use_doc_orientation_classify"] is True
        assert kwargs["use_textline_orientation"] is True

    def test_recognize_joins_lines_and_averages_scores(self):
        engine, _ = _paddle_engine([{"rec_texts": ["one", "two"], "rec_scores": [0.5, 1.0]}])
        array = MagicMock()
        array.shape = (40, 30, 3)

        result = engine.recognize(array)

        assert result == OcrResult(
            text="one\ntwo",
            confidence=pytest.approx(0.75),
            engine="paddleocr 3.0.0",
            language="en",
            image_width=30,
            image_height=40,
            lines=(("one", 0.5), ("two", 1.0)),
        )

    def test_recognize_handles_no_text(self):
        engine, _ = _paddle_engine([])
        array = MagicMock()
        array.shape = (5, 6, 3)

        result = engine.recognize(array)

        assert result.text == ""
        assert result.confidence == 0.0
        assert result.lines == ()

    def test_recognize_reads_dimensions_from_a_file_path(self):
        engine, _ = _paddle_engine([{"rec_texts": ["hi"], "rec_scores": [0.9]}])
        array = MagicMock()
        array.shape = (7, 8, 3)

        with patch("cv2.imread", return_value=array) as imread:
            result = engine.recognize("scan.png")

        imread.assert_called_once_with("scan.png")
        assert (result.image_width, result.image_height) == (8, 7)

    def test_recognize_leaves_dimensions_unset_for_an_unreadable_file(self):
        engine, _ = _paddle_engine([{"rec_texts": ["hi"], "rec_scores": [0.9]}])

        with patch("cv2.imread", return_value=None):
            result = engine.recognize("missing.png")

        assert result.text == "hi"
        assert result.image_width is None
        assert result.image_height is None

    def test_resolve_device_defaults_to_cpu(self):
        assert PaddleOcrEngine.resolve_device(False) == "cpu"

    def test_resolve_device_uses_gpu_when_enabled_and_available(self):
        mock_paddle = MagicMock()
        mock_paddle.device.is_compiled_with_cuda.return_value = True
        mock_paddle.device.cuda.device_count.return_value = 1

        with patch.dict(sys.modules, {"paddle": mock_paddle}):
            assert PaddleOcrEngine.resolve_device(True) == "gpu"

    def test_resolve_device_falls_back_to_cpu_when_enabled_but_unsupported(self):
        mock_paddle = MagicMock()
        mock_paddle.device.is_compiled_with_cuda.return_value = False

        with patch.dict(sys.modules, {"paddle": mock_paddle}):
            assert PaddleOcrEngine.resolve_device(True) == "cpu"
