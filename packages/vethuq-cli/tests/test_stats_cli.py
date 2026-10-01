import io

import vethuq_cli.stats as stats_module
import vethuq_core.db as db_module
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from typer.testing import CliRunner
from vethuq_cli.main import app
from vethuq_core.stats import ProcessingMetric

runner = CliRunner()


def _use_temp_db(monkeypatch, tmp_path):
    db_path = tmp_path / "vethuq.db"
    real_connect = db_module.Db.connect
    monkeypatch.setattr(
        db_module.Db,
        "connect",
        staticmethod(lambda path=None, **kwargs: real_connect(db_path, **kwargs)),
    )
    return db_path


def _seed_metrics(db_path):
    conn = db_module.Db.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO processing_metrics "
            "(file_type, size_bucket, document_count, avg_duration_seconds, avg_peak_memory_mb, "
            "avg_cpu_percent, updated_at) "
            "VALUES ('pdf', 'medium', 2, 5.0, 100.0, 10.0, '2026-01-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO confidence_metrics "
            "(file_type, process_type, page_count, avg_confidence, updated_at) "
            "VALUES ('pdf', 'native', 3, 1.0, '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
    finally:
        conn.close()


def test_show_with_no_statistics(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)

    result = runner.invoke(app, ["stats", "show"])

    assert result.exit_code == 0
    assert "No processing statistics recorded yet." in result.stdout
    assert "No confidence statistics recorded yet." in result.stdout


def test_show_displays_seeded_statistics(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _seed_metrics(db_path)

    result = runner.invoke(app, ["stats", "show"])

    assert result.exit_code == 0
    assert "pdf" in result.stdout
    assert "native" in result.stdout
    assert "100%" in result.stdout


def test_processing_panel_normalizes_cpu_percent_by_core_count(monkeypatch):
    monkeypatch.setattr(stats_module.os, "cpu_count", lambda: 4)
    metric = ProcessingMetric(
        file_type="pdf",
        size_bucket="medium",
        document_count=1,
        avg_duration_seconds=1.0,
        avg_peak_memory_mb=1.0,
        avg_cpu_percent=200.0,
        updated_at="2026-01-01T00:00:00+00:00",
    )

    panel = stats_module._processing_panel([metric])
    buffer = io.StringIO()
    Console(file=buffer, width=120).print(panel)

    assert "50%" in buffer.getvalue()


def test_align_widths_matches_the_widest_panel():
    narrow = Panel(Text("x"), title="A")
    wide = Panel(Text("x" * 50), title="B")
    console = Console(file=io.StringIO(), width=120)

    stats_module._align_widths(console, narrow, wide)

    assert narrow.width == wide.width


def test_reset_declined_leaves_statistics_intact(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _seed_metrics(db_path)

    result = runner.invoke(app, ["stats", "reset"], input="n\n")

    assert result.exit_code == 0
    assert "Statistics reset." not in result.stdout

    conn = db_module.Db.connect(db_path)
    try:
        assert conn.execute("SELECT * FROM processing_metrics").fetchone() is not None
    finally:
        conn.close()


def test_reset_confirmed_clears_statistics(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _seed_metrics(db_path)

    result = runner.invoke(app, ["stats", "reset"], input="y\n")

    assert result.exit_code == 0
    assert "Statistics reset." in result.stdout

    conn = db_module.Db.connect(db_path)
    try:
        assert conn.execute("SELECT * FROM processing_metrics").fetchone() is None
        assert conn.execute("SELECT * FROM confidence_metrics").fetchone() is None
    finally:
        conn.close()


def test_reset_force_skips_confirmation(tmp_path, monkeypatch):
    db_path = _use_temp_db(monkeypatch, tmp_path)
    _seed_metrics(db_path)

    result = runner.invoke(app, ["stats", "reset", "--force"])

    assert result.exit_code == 0
    assert "Statistics reset." in result.stdout

    conn = db_module.Db.connect(db_path)
    try:
        assert conn.execute("SELECT * FROM processing_metrics").fetchone() is None
    finally:
        conn.close()
