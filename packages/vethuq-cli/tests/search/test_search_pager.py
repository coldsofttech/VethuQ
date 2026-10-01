import os

import pytest
from vethuq_cli.search import pager as pager_module
from vethuq_cli.search.pager import Pager


def _fail_on_export():
    raise AssertionError("should not export")


class TestPager:
    def test_page_prints_everything_directly_when_not_a_tty(self, monkeypatch, capsys):
        monkeypatch.setattr(pager_module.sys.stdout, "isatty", lambda: False)

        Pager.page("line one\nline two\nline three", _fail_on_export)

        out = capsys.readouterr().out
        assert out.splitlines() == ["line one", "line two", "line three"]

    def test_page_reveals_one_more_line_on_down_and_quits_on_q(self, monkeypatch):
        monkeypatch.setattr(pager_module.sys.stdout, "isatty", lambda: True)
        monkeypatch.setattr(
            pager_module.shutil, "get_terminal_size", lambda: os.terminal_size((80, 3))
        )
        keys = iter(["down", "quit"])
        monkeypatch.setattr(Pager, "read_key_windows", lambda: next(keys))
        monkeypatch.setattr(Pager, "read_key_posix", lambda: next(keys))
        written: list[str] = []
        monkeypatch.setattr(Pager, "write_line", lambda message: written.append(message))

        with pytest.raises(KeyboardInterrupt):
            Pager.page("l1\nl2\nl3\nl4\nl5", _fail_on_export)

        # terminal_size.lines=3 reserves one line for the status prompt, so the
        # first screen is 2 lines; pressing "down" reveals exactly one more.
        assert written == ["l1", "l2", "l3"]

    def test_page_stops_without_prompting_when_content_fits_one_screen(self, monkeypatch, capsys):
        monkeypatch.setattr(pager_module.sys.stdout, "isatty", lambda: True)
        monkeypatch.setattr(
            pager_module.shutil, "get_terminal_size", lambda: os.terminal_size((80, 10))
        )

        def _fail():
            raise AssertionError("should not read a key when everything already fits")

        monkeypatch.setattr(Pager, "read_key_windows", lambda: _fail())
        monkeypatch.setattr(Pager, "read_key_posix", lambda: _fail())

        Pager.page("l1\nl2\nl3", _fail_on_export)

        assert capsys.readouterr().out.splitlines() == ["l1", "l2", "l3"]

    def test_page_exports_and_closes_on_e(self, monkeypatch):
        monkeypatch.setattr(pager_module.sys.stdout, "isatty", lambda: True)
        monkeypatch.setattr(
            pager_module.shutil, "get_terminal_size", lambda: os.terminal_size((80, 3))
        )
        keys = iter(["export"])
        monkeypatch.setattr(Pager, "read_key_windows", lambda: next(keys))
        monkeypatch.setattr(Pager, "read_key_posix", lambda: next(keys))
        monkeypatch.setattr(Pager, "write_line", lambda message: None)
        exported = []

        Pager.page("l1\nl2\nl3\nl4\nl5", lambda: exported.append(True))

        assert exported == [True]
