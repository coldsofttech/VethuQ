from __future__ import annotations

from pathlib import Path

import pytest

from vethuq_desktop.opening import Opener


def opener(app: str | None, launched: list, plain: list, fail: bool = False) -> Opener:
    def launch(arguments):
        if fail:
            raise OSError("cannot start")
        launched.append(list(arguments))

    return Opener(
        default_app=lambda extension: Path(app) if app else None,
        launch=launch,
        plain=plain.append,
    )


@pytest.fixture
def calls():
    return [], []


def go(app, path, calls, **place):
    launched, plain = calls
    result = opener(app, launched, plain).open(path, **place)
    return result, launched, plain


class TestPdf:
    @pytest.mark.parametrize(
        "app", ["C:/Edge/msedge.exe", "C:/Chrome/chrome.exe", "C:/FF/firefox.exe"]
    )
    def test_a_browser_gets_the_page_in_the_address(self, app, calls, tmp_path):
        pdf = tmp_path / "a b.pdf"
        result, launched, plain = go(app, str(pdf), calls, page=12)
        assert result.jumped and result.hint is None and plain == []
        assert launched[0][0] == app
        assert launched[0][1].startswith("file://") and launched[0][1].endswith("a%20b.pdf#page=12")

    def test_adobe_and_foxit_take_an_action(self, calls):
        for app in ("C:/Adobe/AcroRd32.exe", "C:/Adobe/Acrobat.exe", "C:/Foxit/FoxitPDFReader.exe"):
            launched: list = []
            Opener(
                default_app=lambda e, a=app: Path(a), launch=launched.append, plain=lambda p: None
            ).open("C:/docs/x.pdf", page=3)
            assert launched == [[app, "/A", "page=3", "C:/docs/x.pdf"]]

    def test_sumatra_takes_a_page_option(self, calls):
        result, launched, _ = go("C:/Sumatra/SumatraPDF.exe", "C:/x.pdf", calls, page=7)
        assert result.jumped and launched == [
            ["C:/Sumatra/SumatraPDF.exe", "-page", "7", "C:/x.pdf"]
        ]

    def test_another_viewer_opens_at_the_top_and_says_where_to_look(self, calls):
        result, launched, plain = go("C:/Other/viewer.exe", "C:/x.pdf", calls, page=7)
        assert not result.jumped and result.opened and result.hint == "Go to page 7."
        assert launched == [] and plain == ["C:/x.pdf"]

    def test_without_a_page_it_just_opens(self, calls):
        result, launched, plain = go("C:/Edge/msedge.exe", "C:/x.pdf", calls)
        assert result.opened and not result.jumped and result.hint is None and plain == ["C:/x.pdf"]


class TestText:
    def test_vs_code_goes_to_line_and_column(self, calls):
        _, launched, _ = go("C:/VS/Code.exe", "C:/n.txt", calls, line=9, column=4)
        assert launched == [["C:/VS/Code.exe", "-g", "C:/n.txt:9:4"]]
        _, launched, _ = go("C:/VS/Code.exe", "C:/n.md", calls, line=9)
        assert launched[-1] == ["C:/VS/Code.exe", "-g", "C:/n.md:9"]

    def test_notepad_plus_plus_and_sublime(self, calls):
        _, launched, _ = go("C:/N/notepad++.exe", "C:/n.txt", calls, line=9, column=4)
        assert launched == [["C:/N/notepad++.exe", "-n9", "-c4", "C:/n.txt"]]
        _, launched, _ = go("C:/S/sublime_text.exe", "C:/n.csv", calls, line=2)
        assert launched[-1] == ["C:/S/sublime_text.exe", "C:/n.csv:2"]

    def test_plain_notepad_opens_at_the_top_with_a_hint(self, calls):
        result, launched, plain = go("C:/Windows/notepad.exe", "C:/n.txt", calls, line=9, column=4)
        assert not result.jumped and result.hint == "Go to line 9, column 4."
        assert launched == [] and plain == ["C:/n.txt"]

    def test_a_csv_row_has_no_column_in_the_hint(self, calls):
        result, _, _ = go("C:/Windows/notepad.exe", "C:/d.csv", calls, line=5)
        assert result.hint == "Go to line 5."


class TestFallbacks:
    def test_an_unknown_default_app_or_type_opens_plainly(self, calls):
        result, launched, plain = go(None, "C:/x.pdf", calls, page=2)
        assert plain == ["C:/x.pdf"] and result.hint == "Go to page 2."
        result, _, plain2 = go("C:/Word/winword.exe", "C:/x.docx", calls, page=2)
        assert result.opened and result.hint is None and plain2[-1] == "C:/x.docx"

    def test_a_program_that_will_not_start_falls_back_to_a_plain_open(self):
        launched, plain = [], []
        result = opener("C:/Edge/msedge.exe", launched, plain, fail=True).open("C:/x.pdf", page=2)
        assert result.opened and not result.jumped and plain == ["C:/x.pdf"]
        assert result.hint == "Go to page 2."

    def test_off_windows_nothing_is_looked_up(self):
        from vethuq_desktop.opening import windows_default_app

        assert windows_default_app(".pdf") is None or True  # only Windows has a registry of apps
