import hashlib
import re
import sys
from pathlib import Path

import pytest
from vethuq_ui.fonts import TeluguFont

ASSETS = Path(TeluguFont.fonts_dir())


class TestPick:
    def test_a_native_font_beats_the_bundled_one(self):
        assert TeluguFont.pick(["Arial", "Noto Sans Telugu", "Nirmala UI"]) == "Nirmala UI"

    def test_natives_are_tried_in_order(self):
        assert TeluguFont.pick(["Vani", "Gautami"]) == "Gautami"

    def test_the_bundled_font_is_the_last_resort(self):
        assert TeluguFont.pick(["Arial", "Noto Sans Telugu"]) == "Noto Sans Telugu"

    def test_nothing_suitable_is_none(self):
        assert TeluguFont.pick(["Arial", "Segoe UI"]) is None
        assert TeluguFont.pick([]) is None

    def test_matching_ignores_case_and_returns_the_name_as_installed(self):
        assert TeluguFont.pick(["nirmala ui"]) == "nirmala ui"


class TestNeedsFont:
    def test_only_telugu_text_does(self):
        assert TeluguFont.needs_font("అమ్మ")
        assert TeluguFont.needs_font("invoice అమ్మ")
        assert not TeluguFont.needs_font("invoice total")
        assert not TeluguFont.needs_font("")
        assert not TeluguFont.needs_font("日本語 café")


class TestFontsDir:
    def test_in_the_package_assets_by_default(self):
        assert TeluguFont.fonts_dir().parts[-3:] == ("vethuq_ui", "assets", "fonts")

    def test_beside_the_executables_in_the_installed_app(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "VethuQ-UI.exe"))

        assert TeluguFont.fonts_dir() == tmp_path / "fonts"


class TestLoadBundled:
    @pytest.fixture
    def fonts(self, monkeypatch, tmp_path):
        for name in ("b.ttf", "a.ttf", "OFL.txt", "notes.md"):
            (tmp_path / name).write_bytes(b"x")
        monkeypatch.setattr(TeluguFont, "fonts_dir", staticmethod(lambda: tmp_path))
        return tmp_path

    def test_loads_each_font_file_in_order_and_nothing_else(self, fonts):
        seen = []

        loaded = TeluguFont.load_bundled(lambda path: seen.append(path.name) or 1)

        assert seen == ["a.ttf", "b.ttf"]
        assert [p.name for p in loaded] == ["a.ttf", "b.ttf"]

    def test_a_font_that_fails_to_load_is_skipped_not_fatal(self, fonts):
        loaded = TeluguFont.load_bundled(lambda path: 0 if path.name == "a.ttf" else 1)

        assert [p.name for p in loaded] == ["b.ttf"]

    def test_an_error_loading_one_does_not_stop_the_rest(self, fonts):
        def add(path):
            if path.name == "a.ttf":
                raise OSError("denied")
            return 1

        assert [p.name for p in TeluguFont.load_bundled(add)] == ["b.ttf"]

    def test_a_missing_folder_loads_nothing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(TeluguFont, "fonts_dir", staticmethod(lambda: tmp_path / "none"))

        assert TeluguFont.load_bundled(lambda path: 1) == []

    def test_there_is_nothing_to_load_off_windows(self):
        assert sys.platform == "win32" or TeluguFont._add_private_font(Path("x.ttf")) == 0


class TestResolve:
    def test_a_native_font_is_used_and_the_bundled_one_is_never_loaded(self):
        loaded = []

        family = TeluguFont.resolve(
            lambda: ["Arial", "Nirmala UI"], lambda p: loaded.append(p) or 1
        )

        assert family == "Nirmala UI"
        assert loaded == []

    def test_without_a_native_font_the_bundled_one_is_loaded_and_used(self):
        families = ["Arial"]

        def add(path):
            if "Noto Sans Telugu" not in families:
                families.append("Noto Sans Telugu")
            return 1

        assert TeluguFont.resolve(lambda: list(families), add) == "Noto Sans Telugu"

    def test_when_the_bundled_font_cannot_be_loaded_there_is_no_family(self):
        assert TeluguFont.resolve(lambda: ["Arial"], lambda path: 0) is None

    def test_a_bundled_font_that_is_already_there_is_still_looked_for_a_native_one(self):
        assert (
            TeluguFont.resolve(lambda: ["Noto Sans Telugu"], lambda path: 0) == "Noto Sans Telugu"
        )


class TestBundledFiles:
    def test_the_files_are_present_and_look_like_truetype(self):
        for name in ("NotoSansTelugu-Regular.ttf", "NotoSansTelugu-Bold.ttf"):
            data = (ASSETS / name).read_bytes()

            assert data[:4] == b"\x00\x01\x00\x00"
            assert len(data) > 100_000

    def test_the_license_ships_with_them(self):
        text = (ASSETS / "OFL.txt").read_text(encoding="utf-8")

        assert "SIL OPEN FONT LICENSE Version 1.1" in text
        assert "Noto Project Authors" in text

    def test_the_readme_records_what_the_files_are(self):
        readme = (ASSETS / "README.md").read_text(encoding="utf-8")
        recorded = dict(re.findall(r"`([^`]+\.(?:ttf|txt))` \| `([0-9a-f]{64})`", readme))

        assert set(recorded) == {"NotoSansTelugu-Regular.ttf", "NotoSansTelugu-Bold.ttf", "OFL.txt"}
        for name, digest in recorded.items():
            assert hashlib.sha256((ASSETS / name).read_bytes()).hexdigest() == digest, name
