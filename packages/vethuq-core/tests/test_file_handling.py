import json
import os
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from conftest import PaddleStub
from vethuq_core.ocr import Quick
from vethuq_core.paths.fspath import FsPath
from vethuq_core.readers import Readers
from vethuq_core.search import Export
from vethuq_core.search.search import SearchMatch
from vethuq_core.sources import Source, Sources
from vethuq_core.storage import Storage

SPECIAL_NAMES = [
    "with space.png",
    "it's quoted.png",
    "[brackets] (parens) {braces}.png",
    "100% & more #1.png",
    "semi;colon=plus+tilde~.png",
]
UNICODE_NAMES = [
    "日本語のファイル.png",
    "résumé café.png",
    "Ünïcödé_ñ.png",
    "документ.png",
    "😀.png",
]


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks aren't available here")


def _long_dir(root: Path) -> Path:
    folder = root
    while len(str(folder)) < 300:
        folder = folder / ("d" * 50)
    return folder


def _png_bytes() -> bytes:
    import cv2
    import numpy as np

    return cv2.imencode(".png", np.zeros((4, 4, 3), dtype=np.uint8))[1].tobytes()


def _make_long_file(root: Path, name: str = "long.png") -> Path:
    folder = FsPath.extended(_long_dir(root))
    folder.mkdir(parents=True)
    file_path = FsPath.extended(folder / name)
    file_path.write_bytes(_png_bytes())
    return FsPath.plain(file_path)


def _index(storage: Storage, source_path: Path, text: str = "hello") -> Source:
    engine = PaddleStub()
    engine.predict.return_value = [{"rec_texts": [text], "rec_scores": [0.9]}]
    with patch("vethuq_core.ocr.engines.Engines.get", return_value=engine):
        source = Sources.add(storage, source_path)
        Quick.run(storage, source)
    return source


class TestFsPath:
    def test_short_paths_are_left_alone(self, tmp_path: Path):
        assert FsPath.extended(tmp_path / "a.png") == tmp_path / "a.png"

    @pytest.mark.skipif(sys.platform != "win32", reason="extended-length prefix is Windows-only")
    def test_long_paths_get_the_extended_prefix(self, tmp_path: Path):
        long_path = _long_dir(tmp_path) / "a.png"

        extended = FsPath.extended(long_path)

        assert str(extended).startswith("\\\\?\\")
        assert FsPath.plain(extended) == long_path

    def test_plain_strips_both_prefix_forms(self):
        assert str(FsPath.plain("\\\\?\\C:\\a\\b")) == str(Path("C:\\a\\b"))
        assert str(FsPath.plain("\\\\?\\UNC\\srv\\share\\b")) == str(Path("\\\\srv\\share\\b"))

    def test_is_within_accepts_files_under_the_root(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "a.png").write_bytes(b"x")

        assert FsPath.is_within(tmp_path / "sub" / "a.png", tmp_path)
        assert FsPath.is_within(tmp_path, tmp_path)

    def test_is_within_rejects_dotdot_escape(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        (tmp_path / "outside.png").write_bytes(b"x")

        assert not FsPath.is_within(root / ".." / "outside.png", root)

    def test_is_within_rejects_sibling_with_common_prefix(self, tmp_path: Path):
        (tmp_path / "root").mkdir()
        (tmp_path / "root-other").mkdir()

        assert not FsPath.is_within(tmp_path / "root-other", tmp_path / "root")

    def test_is_within_rejects_symlink_escape(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"x")
        _symlink(root / "link.png", outside)

        assert not FsPath.is_within(root / "link.png", root)

    def test_is_within_rejects_directory_link_escape(self, tmp_path: Path):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "a.png").write_bytes(b"x")
        _symlink(root / "linked", outside, directory=True)

        assert not FsPath.is_within(root / "linked" / "a.png", root)

    @pytest.mark.skipif(sys.platform != "win32", reason="junctions are Windows-only")
    def test_is_within_rejects_junction_escape(self, tmp_path: Path):
        import subprocess

        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "a.png").write_bytes(b"x")
        result = subprocess.run(  # noqa: S603
            ["cmd", "/c", "mklink", "/J", str(root / "junction"), str(outside)],  # noqa: S607
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            pytest.skip("couldn't create a junction here")

        assert not FsPath.is_within(root / "junction" / "a.png", root)


class TestScanning:
    @pytest.mark.parametrize("name", SPECIAL_NAMES + UNICODE_NAMES)
    def test_unusual_names_are_scanned(self, tmp_path: Path, name: str):
        (tmp_path / name).write_bytes(b"x")

        assert list(Readers.iter_files(tmp_path)) == [tmp_path / name]

    def test_unusual_folder_names_are_walked(self, tmp_path: Path):
        folder = tmp_path / "ünï [x] & 100%"
        folder.mkdir()
        (folder / "a b.png").write_bytes(b"x")

        assert list(Readers.iter_files(tmp_path)) == [folder / "a b.png"]

    @pytest.mark.skipif(sys.platform != "win32", reason="long paths need the Windows prefix")
    def test_paths_over_260_characters_are_scanned(self, tmp_path: Path):
        file_path = _make_long_file(tmp_path)
        assert len(str(file_path)) > 260

        found = list(Readers.iter_files(tmp_path))

        assert found == [file_path]
        assert not str(found[0]).startswith("\\\\?\\")

    @pytest.mark.skipif(sys.platform != "win32", reason="long paths need the Windows prefix")
    def test_unsupported_files_over_260_characters_are_found(self, tmp_path: Path):
        file_path = _make_long_file(tmp_path, "notes.xyz")

        assert list(Readers.iter_unsupported_files(tmp_path)) == [file_path]


class TestIndexing:
    @pytest.mark.parametrize("name", [SPECIAL_NAMES[1], SPECIAL_NAMES[3], UNICODE_NAMES[0]])
    def test_unusual_names_are_indexed_and_stored_unchanged(
        self, conn: sqlite3.Connection, storage: Storage, tmp_path: Path, name: str
    ):
        folder = tmp_path / "src"
        folder.mkdir()
        (folder / name).write_bytes(b"fake png bytes")

        _index(storage, folder, "naïve café 日本語 100%")

        row = conn.execute("SELECT file_path, status FROM document_index").fetchone()
        assert row["status"] == "indexed"
        assert Path(row["file_path"]).name == name
        text = conn.execute("SELECT ocr_text FROM image_pages").fetchone()["ocr_text"]
        assert text == "naïve café 日本語 100%"

    @pytest.mark.skipif(sys.platform != "win32", reason="long paths need the Windows prefix")
    def test_long_path_file_is_indexed(
        self, conn: sqlite3.Connection, storage: Storage, tmp_path: Path
    ):
        folder = tmp_path / "src"
        folder.mkdir()
        file_path = _make_long_file(folder)

        _index(storage, folder)

        row = conn.execute(
            "SELECT file_path, status, file_size_bytes FROM document_index"
        ).fetchone()
        assert row["status"] == "indexed"
        assert row["file_path"] == str(file_path)
        assert row["file_size_bytes"] == len(_png_bytes())

    def test_symlink_escaping_the_source_is_recorded_as_an_error(
        self, conn: sqlite3.Connection, storage: Storage, tmp_path: Path
    ):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"secret")
        _symlink(root / "link.png", outside)

        _index(storage, root)

        row = conn.execute("SELECT status, error_message FROM document_index").fetchone()
        assert row["status"] == "error"
        assert "outside its source" in row["error_message"]
        assert conn.execute("SELECT COUNT(*) FROM image_pages").fetchone()[0] == 0

    def test_symlinked_folder_escaping_the_source_is_recorded_as_an_error(
        self, conn: sqlite3.Connection, storage: Storage, tmp_path: Path
    ):
        root = tmp_path / "root"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "a.png").write_bytes(b"secret")
        _symlink(root / "linked", outside, directory=True)

        _index(storage, root)

        rows = conn.execute("SELECT status FROM document_index").fetchall()
        assert all(row["status"] == "error" for row in rows)
        assert conn.execute("SELECT COUNT(*) FROM image_pages").fetchone()[0] == 0


def _match(name: str, path: str, matched: str = "amount") -> SearchMatch:
    return SearchMatch(
        file_id=1,
        file_name=name,
        file_path=path,
        page_number=1,
        total_pages=1,
        before="Total ",
        matched=matched,
        after=" due",
        truncated_before=False,
        truncated_after=False,
        duplicate_of_path=None,
    )


class TestExportNames:
    def test_json_export_keeps_unicode_unescaped(self, tmp_path: Path):
        output = tmp_path / "out.json"
        path = str(tmp_path / "日本語 résumé.png")

        Export.search_results(
            [_match("日本語 résumé.png", path, "日本語")], "日本語", output, "json"
        )

        text = output.read_text(encoding="utf-8")
        assert "日本語 résumé.png" in text
        assert json.loads(text)["matches"][0]["file_name"] == "日本語 résumé.png"

    def test_html_export_escapes_special_names_and_keeps_unicode(self, tmp_path: Path):
        output = tmp_path / "out.html"
        name = "it's q <b> & 100% #1 [x] ünï.png"
        path = str(tmp_path / name)

        Export.search_results([_match(name, path)], "amount", output, "html")

        html_text = output.read_text(encoding="utf-8")
        assert "<b>" not in html_text.split("<body", 1)[1].replace("<mark>", "")
        assert "ünï.png" in html_text
        assert "&amp; 100%" in html_text

    def test_file_uri_percent_encodes_special_characters(self, tmp_path: Path):
        uri = Export._file_uri(str(tmp_path / "a b#c%d&é.png"))

        assert uri.startswith("file:")
        assert "%20" in uri and "%23" in uri and "%25" in uri
        assert " " not in uri and "#c" not in uri

    @pytest.mark.skipif(sys.platform != "win32", reason="long paths need the Windows prefix")
    def test_file_uri_for_long_paths_has_no_extended_prefix(self, tmp_path: Path):
        file_path = _make_long_file(tmp_path)

        uri = Export._file_uri(str(file_path))

        assert "%3F" not in uri and "?" not in uri
        assert os.path.basename(str(file_path)) in uri
