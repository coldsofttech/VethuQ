import pymupdf
import pytest
from vethuq_core.readers import (
    CorruptedFileError,
    FileRemovedError,
    PasswordProtectedError,
    PdfReader,
)


class TestPdfReaderErrors:
    def test_raises_file_removed_for_missing_file(self, tmp_path):
        with pytest.raises(FileRemovedError, match="removed during indexing"):
            list(PdfReader().read(tmp_path / "gone.pdf"))

    def test_raises_corrupted_for_unparseable_file(self, tmp_path):
        bad = tmp_path / "bad.pdf"
        bad.write_bytes(b"this is not a pdf at all")
        with pytest.raises(CorruptedFileError, match="corrupted"):
            list(PdfReader().read(bad))

    def test_raises_password_protected_for_encrypted_file(self, tmp_path):
        encrypted = tmp_path / "locked.pdf"
        doc = pymupdf.open()
        doc.new_page().insert_text((72, 72), "secret")
        doc.save(
            encrypted,
            encryption=pymupdf.PDF_ENCRYPT_AES_256,
            user_pw="pw",
            owner_pw="pw",
        )
        doc.close()
        with pytest.raises(PasswordProtectedError, match="password-protected"):
            list(PdfReader().read(encrypted))
