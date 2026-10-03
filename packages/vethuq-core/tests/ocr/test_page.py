from unittest.mock import MagicMock, patch

from vethuq_core.ocr import PageOcr
from vethuq_core.ocr.engines import OcrResult
from vethuq_core.readers import ReadPage
from vethuq_core.storage import Storage

NATIVE = "This is a real paragraph of page content."


def _result(text: str, confidence: float = 0.9) -> OcrResult:
    return OcrResult(
        text=text,
        confidence=confidence,
        engine="fake",
        language="en",
        image_width=10,
        image_height=20,
    )


class TestPageOcr:
    def test_is_native_text_threshold(self):
        assert not PageOcr.is_native_text("")
        assert not PageOcr.is_native_text("p.3")
        assert not PageOcr.is_native_text("a-long-single-token-with-no-spaces-at-all")
        assert PageOcr.is_native_text(NATIVE)

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_native_page_skips_the_engine(self, mock_get: MagicMock, storage: Storage):
        render = MagicMock()
        page = ReadPage(native_text=NATIVE, image_regions=(), render=render)

        result = PageOcr.ocr_page(storage, page)

        assert (result.source, result.confidence, result.text) == ("native", 1.0, NATIVE)
        mock_get.assert_not_called()
        render.assert_not_called()

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_scanned_page_renders_whole_page_and_runs_ocr(
        self, mock_get: MagicMock, storage: Storage
    ):
        mock_get.return_value.recognize.return_value = _result("scanned")
        render = MagicMock(return_value="image")
        page = ReadPage(native_text="", image_regions=(), render=render)

        result = PageOcr.ocr_page(storage, page)

        render.assert_called_once_with(None)
        mock_get.return_value.recognize.assert_called_once_with("image")
        assert (result.source, result.text, result.ocr_engine) == ("ocr", "scanned", "fake")

    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_mixed_page_ocrs_only_image_regions(self, mock_get: MagicMock, storage: Storage):
        mock_get.return_value.recognize.side_effect = [_result("one", 0.8), _result("two", 0.6)]
        render = MagicMock(side_effect=lambda region: f"img{region}")
        regions = ((0, 0, 1, 1), (2, 2, 3, 3))
        page = ReadPage(native_text=NATIVE, image_regions=regions, render=render)

        result = PageOcr.ocr_page(storage, page)

        assert result.source == "mixed"
        assert result.text == f"{NATIVE}\none\ntwo"
        assert abs(result.confidence - 0.7) < 1e-9
        assert [call.args[0] for call in render.call_args_list] == list(regions)
