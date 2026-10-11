from __future__ import annotations

import json


def test_the_commands_appear_in_the_vethuq_command_line(cli):
    out = cli("background", "--help").output
    for word in ("install", "uninstall", "start", "stop", "pause", "resume", "status", "host"):
        assert word in out


def test_status_before_an_install(cli):
    result = cli("--json", "background", "status")
    data = json.loads(result.output)
    assert data["state"] in ("not_installed", "unsupported") and data["running"] is False


def test_host_once_works_the_queue(cli, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("hello")
    cli("source", "add", str(docs))
    assert "Queued request 1" in cli("index", "submit").output
    out = cli("background", "host", "--once").output
    assert "Worked 1 request" in out
    assert "completed" in cli("index", "queue", "show", "1").output


def test_while_the_host_is_not_running_index_run_runs_here(cli, tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.txt").write_text("hello")
    cli("source", "add", str(docs))
    assert "completed" in cli("index", "run").output
