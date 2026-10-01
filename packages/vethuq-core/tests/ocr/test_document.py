import sys
from unittest.mock import patch

from vethuq_core.ocr import Document


class _FakeStat:
    """A minimal stand-in for `os.stat_result` that only defines the
    attributes it's given - so `hasattr(fake_stat, "st_birthtime")` behaves
    like it would on a platform that doesn't expose that field at all."""

    def __init__(self, **attrs):
        for name, value in attrs.items():
            setattr(self, name, value)


class TestDocument:
    def test_has_content_changed_skips_hash_when_mtime_and_size_unchanged(self, tmp_path):
        file_path = tmp_path / "scan.png"
        file_path.write_bytes(b"unchanged")
        stat = file_path.stat()
        existing = {
            "mtime": stat.st_mtime,
            "file_size_bytes": stat.st_size,
            "sha256": "irrelevant",
        }

        with patch("vethuq_core.ocr.Document.compute_sha256") as mock_checksum:
            assert Document.has_content_changed(file_path, existing) is False
            mock_checksum.assert_not_called()

    def test_has_content_changed_true_when_checksum_differs_despite_same_size(self, tmp_path):
        file_path = tmp_path / "scan.png"
        file_path.write_bytes(b"aaaaaaaaa")
        stat = file_path.stat()
        existing = {
            "mtime": stat.st_mtime - 10,
            "file_size_bytes": stat.st_size,
            "sha256": "not-the-real-checksum",
        }

        assert Document.has_content_changed(file_path, existing) is True

    def test_capture_timestamps_uses_st_birthtime_when_available(self):
        fake_stat = _FakeStat(st_mtime=1_700_000_000.0, st_birthtime=1_600_000_000.0)

        created_at, modified_at = Document.capture_timestamps(fake_stat)

        assert created_at != modified_at

    def test_capture_timestamps_falls_back_to_mtime_without_birthtime(self):
        fake_stat = _FakeStat(st_mtime=1_700_000_000.0)
        assert not hasattr(fake_stat, "st_birthtime")

        with patch.object(sys, "platform", "linux"):
            created_at, modified_at = Document.capture_timestamps(fake_stat)

        assert created_at == modified_at

    def test_capture_timestamps_uses_st_ctime_on_windows_without_birthtime(self):
        fake_stat = _FakeStat(st_mtime=1_700_000_000.0, st_ctime=1_600_000_000.0)
        assert not hasattr(fake_stat, "st_birthtime")

        with patch.object(sys, "platform", "win32"):
            created_at, modified_at = Document.capture_timestamps(fake_stat)

        assert created_at != modified_at
