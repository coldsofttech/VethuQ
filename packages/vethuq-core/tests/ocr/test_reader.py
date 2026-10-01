from vethuq_core.ocr import PdfReader


class TestPdfReader:
    def test_is_native_text_threshold(self):
        assert not PdfReader.is_native_text("")
        assert not PdfReader.is_native_text("p.3")
        assert not PdfReader.is_native_text("a-long-single-token-with-no-spaces-at-all")
        assert PdfReader.is_native_text("This is a real paragraph of page content.")
