from vethuq_core.sources import Source, SourceFile, SourceSort


def _source(id_: int, path: str, status: str = "active", source_type: str = "folder") -> Source:
    return Source(
        id=id_,
        path=path,
        source_type=source_type,
        status=status,
        added_at="2026-01-01T00:00:00+00:00",
        last_scanned_at=None,
        is_active=True,
        removed_at=None,
    )


def _file(id_: int, path: str, status: str = "indexed") -> SourceFile:
    return SourceFile(
        id=id_,
        file_path=path,
        file_type="pdf",
        status=status,
        error_message=None,
        file_size_bytes=None,
        started_at=None,
        completed_at=None,
        indexed_at=None,
        duration=None,
        retry_count=0,
        confidence=None,
        duplicate_of_path=None,
        pages=0,
        ocr_phase=None,
        ocr_angles=[],
        phase_timings=[],
    )


class TestFileName:
    def test_folder_source_uses_the_relative_path(self, tmp_path):
        source = _source(1, str(tmp_path))
        file = _file(1, str(tmp_path / "sub" / "a.pdf"))

        assert SourceSort.file_name(source, file) == "sub/a.pdf"

    def test_file_source_uses_just_the_name(self, tmp_path):
        source = _source(1, str(tmp_path / "a.pdf"), source_type="file")

        assert SourceSort.file_name(source, _file(1, str(tmp_path / "a.pdf"))) == "a.pdf"

    def test_file_outside_the_folder_falls_back_to_its_name(self, tmp_path):
        source = _source(1, str(tmp_path / "inside"))

        assert SourceSort.file_name(source, _file(1, str(tmp_path / "other" / "x.pdf"))) == "x.pdf"


class TestSortFiles:
    def _files(self, tmp_path):
        source = _source(1, str(tmp_path))
        files = [
            _file(2, str(tmp_path / "b.pdf"), "failed"),
            _file(3, str(tmp_path / "A.pdf"), "indexed"),
            _file(1, str(tmp_path / "c.pdf"), "pending"),
        ]
        return source, files

    def test_filename_ignores_case(self, tmp_path):
        source, files = self._files(tmp_path)

        result = SourceSort.files(source, files, SourceSort.Order.ASC, SourceSort.By.FILENAME)

        assert [f.id for f in result] == [3, 2, 1]

    def test_id_descending(self, tmp_path):
        source, files = self._files(tmp_path)

        result = SourceSort.files(source, files, SourceSort.Order.DESC, SourceSort.By.ID)

        assert [f.id for f in result] == [3, 2, 1]

    def test_status(self, tmp_path):
        source, files = self._files(tmp_path)

        result = SourceSort.files(source, files, SourceSort.Order.ASC, SourceSort.By.STATUS)

        assert [f.status for f in result] == ["failed", "indexed", "pending"]


class TestSortSources:
    SOURCES = [_source(2, "/b", "removed"), _source(3, "/A", "active"), _source(1, "/c", "paused")]

    def test_filename_sorts_by_registered_path(self):
        result = SourceSort.sources(self.SOURCES, SourceSort.Order.ASC, SourceSort.By.FILENAME)

        assert [s.id for s in result] == [3, 2, 1]

    def test_id_descending(self):
        result = SourceSort.sources(self.SOURCES, SourceSort.Order.DESC, SourceSort.By.ID)

        assert [s.id for s in result] == [3, 2, 1]

    def test_status(self):
        result = SourceSort.sources(self.SOURCES, SourceSort.Order.ASC, SourceSort.By.STATUS)

        assert [s.status for s in result] == ["active", "paused", "removed"]

    def test_does_not_modify_the_input(self):
        SourceSort.sources(self.SOURCES, SourceSort.Order.DESC, SourceSort.By.ID)

        assert [s.id for s in self.SOURCES] == [2, 3, 1]
