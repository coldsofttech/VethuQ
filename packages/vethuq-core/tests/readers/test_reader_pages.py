from pathlib import Path

import pymupdf
import pytest
from vethuq_core.readers import (
    ImagePageStorage,
    ImageReader,
    JpgReader,
    PdfPageStorage,
    PdfReader,
    PngReader,
    Readers,
)


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
        assert Readers.file_type_weight("pdf") > Readers.file_type_weight("image")
        assert Readers.file_type_weight("unregistered") == 1.0

    def test_new_file_type_counts_zeroed(self):
        assert Readers.new_file_type_counts() == {"pdf": 0, "image": 0}

    def test_iter_files_yields_only_supported(self, tmp_path: Path):
        (tmp_path / "a.pdf").write_bytes(b"")
        (tmp_path / "b.txt").write_bytes(b"")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.png").write_bytes(b"")

        found = {path.name for path in Readers.iter_files(tmp_path)}

        assert found == {"a.pdf", "c.png"}
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
