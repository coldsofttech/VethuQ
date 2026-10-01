"""Fixtures for the desktop UI tests.

These need Tk and a display. Without `tkinter` the tests aren't collected at all; with
`tkinter` but no display (e.g. a headless Linux box without Xvfb) they skip.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

try:
    import tkinter as tk
except ImportError:  # no Tk in this Python
    tk = None
    collect_ignore_glob = ["*/test_*.py"]


def _skip_without_display(exc: Exception) -> None:
    """Skip for a missing display only - any other Tcl error is a real failure."""
    message = str(exc)
    if "display" in message:
        pytest.skip(f"no display available: {message}")
    raise exc


@pytest.fixture(autouse=True)
def _fresh_icon_cache():
    """Icons are Tk images, which belong to the root that made them - not shareable across
    the per-test roots, so start every test with an empty icon cache."""
    from vethuq_ui import icons

    icons._icon_cache.clear()


@pytest.fixture
def root():
    """A bare themed Tk root, for testing a single widget."""
    import sv_ttk

    try:
        window = tk.Tk()
    except tk.TclError as exc:
        _skip_without_display(exc)
    sv_ttk.set_theme("light")
    yield window
    window.destroy()


@pytest.fixture
def conn(tmp_path):
    from vethuq_core.db import Db

    connection = Db.connect(tmp_path / "vethuq.db")
    yield connection
    connection.close()


@pytest.fixture
def window(tmp_path, monkeypatch):
    """The real `MainWindow` over a temp database, with the index worker never spawned."""
    from vethuq_core.index import IndexRunner
    from vethuq_ui.app import MainWindow

    monkeypatch.setattr(IndexRunner, "start_run", staticmethod(lambda *a, **k: 0))
    try:
        main_window = MainWindow(db_path=tmp_path / "vethuq.db")
    except tk.TclError as exc:
        _skip_without_display(exc)
    main_window.update()
    yield main_window
    main_window.destroy()


@pytest.fixture
def seed_document():
    """Returns `seed(conn, source_id, path, text=None, status='indexed')`, inserting an
    indexed PDF document (with one OCR page when `text` is given) and returning its row id."""

    def seed(
        conn: sqlite3.Connection,
        source_id: int,
        path: str | Path,
        text: str | None = "some text",
        status: str = "indexed",
    ) -> int:
        document_id = conn.execute(
            "INSERT INTO documents (created_at) VALUES ('2026-01-01')"
        ).lastrowid
        row_id = conn.execute(
            "INSERT INTO document_index (source_id, document_id, file_path, file_type, status) "
            "VALUES (?, ?, ?, 'pdf', ?)",
            (source_id, document_id, str(path), status),
        ).lastrowid
        if text is not None:
            conn.execute(
                "INSERT INTO pdf_pages (document_id, page_number, ocr_text, confidence) "
                "VALUES (?, 1, ?, 0.9)",
                (row_id, text),
            )
        conn.commit()
        assert row_id is not None
        return row_id

    return seed


@pytest.fixture
def add_source(window, tmp_path):
    """Registers a folder as a source through the window's real source list; returns its id."""

    def add(name: str = "docs") -> int:
        folder = tmp_path / name
        folder.mkdir(exist_ok=True)
        window.sources.add_source(str(folder))
        row = window.conn.execute(
            "SELECT id FROM sources WHERE path = ?", (str(folder.resolve()),)
        ).fetchone()
        return row["id"]

    return add
