import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pymupdf
import pytest
from vethuq_core.ocr import Quick
from vethuq_core.readers import (
    DocumentReader,
    ImagePageStorage,
    ImageReader,
    JpgReader,
    PdfPageStorage,
    PdfReader,
    PngReader,
    Readers,
    ReadPage,
)
from vethuq_core.sources import Sources
from vethuq_core.storage import Storage

FIXTURES_DIR = Path(__file__).parent.parent / "integration" / "fixtures" / "pdf"


def _make_pdf(path: Path, pages: list[str]) -> None:
    doc = pymupdf.open()
    for text in pages:
        doc.new_page().insert_text((72, 72), text)
    doc.save(path)
    doc.close()


class TestReadersRegistry:
    def test_for_path_picks_reader_by_extension(self):
        assert isinstance(Readers.for_path(Path("a.PDF")), PdfReader)
        assert isinstance(Readers.for_path(Path("a.png")), PngReader)
        assert isinstance(Readers.for_path(Path("a.jpg")), JpgReader)
        assert isinstance(Readers.for_path(Path("a.jpeg")), JpgReader)

    def test_for_path_unknown_extension_raises(self):
        with pytest.raises(KeyError):
            Readers.for_path(Path("a.xyz"))

    def test_for_file_type(self):
        assert isinstance(Readers.for_file_type("pdf"), PdfReader)
        assert isinstance(Readers.for_file_type("image"), ImageReader)
        with pytest.raises(KeyError):
            Readers.for_file_type("nope")

    def test_storage_and_weight_declared_per_reader(self):
        assert isinstance(Readers.for_file_type("pdf").storage, PdfPageStorage)
        assert isinstance(Readers.for_file_type("image").storage, ImagePageStorage)
        assert Readers.file_type_weight("pdf") == 1.5
        assert Readers.file_type_weight("image") == 1.0
        assert Readers.file_type_weight("unregistered") == 1.0

    def test_new_file_type_counts_zeroed(self):
        assert Readers.new_file_type_counts() == {"pdf": 0, "image": 0}

    def test_iter_files_yields_only_supported(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        for name in ("a.pdf", "b.PNG", "sub/c.jpeg", "b.txt"):
            (tmp_path / name).write_bytes(b"x")

        found = {p.relative_to(tmp_path).as_posix() for p in Readers.iter_files(tmp_path)}

        assert found == {"a.pdf", "b.PNG", "sub/c.jpeg"}
        assert list(Readers.iter_files(tmp_path / "b.txt")) == []
        assert list(Readers.iter_files(tmp_path / "a.pdf")) == [tmp_path / "a.pdf"]


class TestReaders:
    def test_image_reader_yields_one_page_rendering_the_file_path(self, tmp_path: Path):
        image = tmp_path / "scan.png"
        image.write_bytes(b"")

        pages = list(Readers.for_path(image).read(image))

        assert len(pages) == 1
        assert pages[0].native_text == ""
        assert pages[0].image_regions == ()
        assert pages[0].render(None) == str(image)

    def test_pdf_reader_yields_native_text_per_page(self, tmp_path: Path):
        pdf = tmp_path / "doc.pdf"
        _make_pdf(pdf, ["first page text", "second page text"])

        pages = list(PdfReader().read(pdf))

        assert [page.native_text.strip() for page in pages] == [
            "first page text",
            "second page text",
        ]
        assert all(page.image_regions == () for page in pages)

    def test_pdf_reader_single_page(self, tmp_path: Path):
        pdf = tmp_path / "doc.pdf"
        _make_pdf(pdf, ["first page text", "second page text"])

        pages = list(PdfReader().read(pdf, page_number=2))

        assert [page.native_text.strip() for page in pages] == ["second page text"]

    def test_pdf_reader_extracts_native_text_without_any_ocr(self):
        pages = list(PdfReader().read(FIXTURES_DIR / "03_Digital Formal Letter.pdf"))

        assert pages
        assert all(len(page.native_text.split()) > 3 for page in pages)
        assert all(page.image_regions == () for page in pages)

    def test_pdf_reader_renders_a_page_to_a_pixel_array(self):
        # Pages are only valid while their iterator is alive (it owns the open file).
        pages = PdfReader().read(FIXTURES_DIR / "01_Digital Invoice.pdf")

        rendered = next(pages).render(None)

        assert rendered.ndim == 3 and rendered.shape[2] == 3

    def test_pdf_reader_reports_embedded_images_on_a_scanned_page(self):
        pages = list(PdfReader().read(FIXTURES_DIR / "05_Scanned Document.pdf"))

        assert any(page.image_regions for page in pages)


class TestReaderIsolation:
    def test_reading_does_not_import_ocr_or_engines(self):
        # `readers` must be usable on its own - importing it and reading a PDF may not
        # drag in the OCR pipeline or any engine.
        pdf = FIXTURES_DIR / "03_Digital Formal Letter.pdf"
        code = (
            "import sys\n"
            "from pathlib import Path\n"
            "from vethuq_core.readers import PdfReader\n"
            f"list(PdfReader().read(Path({str(pdf)!r})))\n"
            "loaded = [m for m in sys.modules if m.startswith(('vethuq_core.ocr', 'paddle'))]\n"
            "assert not loaded, loaded\n"
        )
        subprocess.run([sys.executable, "-c", code], check=True)


class _TextReader(DocumentReader):
    """A stand-in new format: a .txt file is a single page of native text."""

    file_type = "image"  # the schema's file_type set is fixed, so reuse an existing label
    storage = ImagePageStorage()

    def read(self, file_path: Path, page_number: int | None = None) -> Iterator[ReadPage]:
        text = file_path.read_text()
        yield ReadPage(native_text=text, image_regions=(), render=lambda region: text)


class TestNewReader:
    @patch("vethuq_core.ocr.engines.Engines.get")
    def test_plugs_into_the_pipeline_without_ocr_changes(
        self, mock_get_engine, conn: sqlite3.Connection, storage: Storage, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(Readers, "_BY_SUFFIX", dict(Readers._BY_SUFFIX))
        Readers.register(".txt", _TextReader())
        path = tmp_path / "note.txt"
        path.write_text("A native line of text that needs no OCR at all.")
        source = Sources.add(storage, path)

        Quick.run(storage, source)

        # Native text is taken straight from the reader - the engine is never touched.
        mock_get_engine.assert_not_called()
        row = conn.execute("SELECT ocr_text, confidence FROM image_pages").fetchone()
        assert row["ocr_text"] == "A native line of text that needs no OCR at all."
        assert row["confidence"] == 1.0
