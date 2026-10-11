from __future__ import annotations

import pytest

from vethuq._db.values import _PageSource
from vethuq._ocr import _PageOcr
from vethuq_addon_api import LanguageSpec, ReadPage
from vethuq_addon_api.testing import FakeExecutor

EN = LanguageSpec("en", "English", default=True)
LOTS = "There is plenty of real text on this page."


def page(text="", regions=0, image="img"):
    return ReadPage(
        native_text=text,
        image_regions=tuple((float(i), 0.0, 1.0, 1.0) for i in range(regions)),
        render=lambda region: image if region is None else f"{image}-{int(region[0])}",
    )


class TestHasText:
    @pytest.mark.parametrize("text", ["", "   ", "short", "Page 1", "aaaaaaaaaaaaaaaaaaaaaaaaa"])
    def test_too_little(self, text):
        assert not _PageOcr.has_text(text)

    def test_enough(self):
        assert _PageOcr.has_text(LOTS)
        assert _PageOcr.has_text(f"  {LOTS}  ")


class TestTextOnlyPage:
    def test_a_short_text_only_page_is_never_ocrd(self):
        text_only = ReadPage(native_text="Hi", image_regions=(), render=lambda r: "x", ocr=False)
        assert not _PageOcr.needs_ocr(text_only)
        result = _PageOcr.read_page(1, text_only, None)
        assert (result.text, result.source) == ("Hi", _PageSource.NATIVE)

    def test_an_empty_text_only_page_is_native(self):
        empty = ReadPage(native_text="", image_regions=(), render=lambda r: "x", ocr=False)
        assert _PageOcr.read_page(1, empty, None).source is _PageSource.NATIVE


class TestReadPage:
    def test_a_native_page_needs_no_engine(self):
        result = _PageOcr.read_page(1, page(LOTS), None)
        assert (result.text, result.confidence, result.source) == (LOTS, 1.0, _PageSource.NATIVE)
        assert result.quick is None

    def test_a_scanned_page_is_read_whole(self):
        executor = FakeExecutor({"2:0": "scanned words"}, confidence=0.7)
        result = _PageOcr.read_page(2, page(image="img"), executor, EN)
        assert (result.text, result.source) == ("scanned words", _PageSource.OCR)
        assert result.confidence == 0.7 and result.quick.region_count == 0
        assert result.quick.engine == "fake-executor 1.0"
        assert [(r.key, r.image, r.language, r.phase) for r in executor.seen] == [
            ("2:0", "img", EN, "quick")
        ]

    def test_a_scanned_page_that_ocr_cannot_read_keeps_its_little_text(self):
        executor = FakeExecutor()
        result = _PageOcr.read_page(1, page("Page 3", image="x"), executor, EN)
        assert (result.text, result.source, result.confidence) == ("Page 3", _PageSource.OCR, 0.0)

    def test_a_mixed_page_reads_only_regions(self):
        executor = FakeExecutor({"1:0": "first", "1:1": "second"}, confidence=0.5)
        result = _PageOcr.read_page(1, page(LOTS, regions=2), executor, EN)
        assert result.source is _PageSource.MIXED
        assert result.text == f"{LOTS}\nfirst\nsecond"
        assert [r.image for r in executor.seen] == ["img-0", "img-1"]
        assert result.quick.region_count == 2

    def test_a_mixed_page_with_unreadable_images_is_native_text(self):
        result = _PageOcr.read_page(1, page(LOTS, regions=1), FakeExecutor(), EN)
        assert (result.text, result.confidence) == (LOTS, 1.0)

    def test_a_page_needing_ocr_without_an_executor_raises(self):
        with pytest.raises(LookupError):
            _PageOcr.read_page(1, page(), None, EN)
        with pytest.raises(LookupError):
            _PageOcr.read_page(1, page(), FakeExecutor(), None)

    def test_a_native_page_never_asks_the_executor(self):
        executor = FakeExecutor()
        _PageOcr.read_page(1, page(LOTS), executor, EN)
        assert executor.seen == []


class TestTextOnlyPageWithPictures:
    def picture_page(self, files, readable=None):
        return ReadPage(
            native_text="Hi",
            image_regions=tuple((float(i), 0.0, float(i) + 1.0, 1.0) for i in range(len(files))),
            render=lambda region: f"img-{int(region[0])}",
            ocr=False,
            region_files=tuple(files),
            details={"encoding": "utf-8"},
        )

    def test_only_the_pictures_are_read_and_added_to_the_text(self):
        from pathlib import Path

        read = self.picture_page([Path("a.png"), Path("b.png")])
        assert _PageOcr.needs_ocr(read)
        executor = FakeExecutor({"1:0": "first", "1:1": "second"}, confidence=0.9)
        result = _PageOcr.read_page(1, read, executor, EN)
        assert result.source is _PageSource.MIXED
        assert result.text == "Hi\nfirst\nsecond"
        assert result.details == {"encoding": "utf-8"}

    def test_a_picture_nothing_can_read_is_dropped_and_logged(self, caplog):
        from pathlib import Path

        read = self.picture_page([Path("a.png"), Path("b.tif")])
        with caplog.at_level("WARNING", logger="vethuq.indexing"):
            kept = _PageOcr.readable_regions(
                read, Path("n.md"), lambda f: f.suffix == ".png", warn=True
            )
        assert kept.region_files == (Path("a.png"),) and len(kept.image_regions) == 1
        assert kept.render(kept.image_regions[0]) == "img-0"
        assert [r.getMessage() for r in caplog.records if "b.tif" in r.getMessage()]

    def test_with_no_picture_left_the_page_is_native(self):
        from pathlib import Path

        read = self.picture_page([Path("a.png")])
        kept = _PageOcr.readable_regions(read, Path("n.md"), lambda f: False, warn=False)
        assert not _PageOcr.needs_ocr(kept)
        assert _PageOcr.read_page(1, kept, None).source is _PageSource.NATIVE

    def test_without_a_filter_the_page_is_unchanged(self):
        from pathlib import Path

        read = self.picture_page([Path("a.png")])
        assert _PageOcr.readable_regions(read, Path("n.md"), None, warn=True) is read
