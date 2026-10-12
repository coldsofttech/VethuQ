"""`--export` and `--format` on the listing commands, and `--format` on `search`."""

from __future__ import annotations

import json
import re

import pytest

LISTINGS = [
    (("source", "list"), "sources"),
    (("file-types", "list"), "file_types"),
    (("search-engines", "list"), "engines"),
    (("search-engines", "normalizers"), "normalizers"),
    (("languages", "list"), "languages"),
    (("tiers", "list"), "tiers"),
    (("addons", "list"), "addons"),
    (("ocr", "engines"), "engines"),
    (("ocr", "phases"), "phases"),
    (("index", "queue", "list"), "requests"),
    (("index", "history"), "runs"),
    (("index", "jobs"), "jobs"),
    (("credits", "history"), "movements"),
    (("stats", "failures"), "failures"),
    (("stats", "show"), "stats"),
    (("stats", "low-confidence"), "pages"),
]


@pytest.mark.parametrize(("command", "key"), LISTINGS)
def test_a_listing_can_be_written_as_json_or_html(run, tmp_path, command, key):
    as_json = tmp_path / "out.json"
    result = run(*command, "--export", str(as_json), "--format", "json")
    assert result.exit_code == 0, result.output
    payload = json.loads(as_json.read_text(encoding="utf-8"))
    assert payload["count"] == len(payload[key]) and "generated_at" in payload

    as_html = tmp_path / "out.html"
    result = run(*command, "--export", str(as_html), "--format", "html")
    assert result.exit_code == 0, result.output
    text = as_html.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>") and "{{" not in text
    assert text.count("<script>") == 1


def test_the_saved_format_is_used_when_none_is_given(run, tmp_path):
    out = tmp_path / "types.out"
    assert run("file-types", "list", "--export", str(out)).exit_code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["count"] > 0


def test_nothing_is_printed_as_a_table_when_exporting(run, tmp_path):
    result = run("file-types", "list", "--export", str(tmp_path / "t.json"))
    assert "Wrote" in result.output and "extensions" not in result.output


def test_format_needs_export(run):
    result = run("file-types", "list", "--format", "html")
    assert result.exit_code != 0 and "--format needs --export" in result.output


def test_a_bad_format_is_refused(run, tmp_path):
    result = run("file-types", "list", "--export", str(tmp_path / "t"), "--format", "pdf")
    assert result.exit_code != 0 and not (tmp_path / "t").exists()


def test_json_output_names_the_file(run_json, tmp_path):
    data = run_json("file-types", "list", "--export", str(tmp_path / "t.json"))
    assert data["path"].endswith("t.json")


def test_listing_without_export_is_unchanged(run):
    out = run("file-types", "list").output
    assert "Wrote" not in out and "pdf" in out


def test_source_files_are_exported_with_filters(run, docs, tmp_path):
    run("source", "add", str(docs))
    run("index", "run")
    out = tmp_path / "files.html"
    assert (
        run(
            "source", "files", "1", "--detailed", "--export", str(out), "--format", "html"
        ).exit_code
        == 0
    )
    text = out.read_text(encoding="utf-8")
    assert "a.txt" in text and '<span class="pill ok">indexed</span>' in text
    assert re.search(r'<tr data-facets="[^"]*file_type', text)


def test_search_takes_a_format_with_export(run, docs, tmp_path):
    run("source", "add", str(docs))
    run("index", "run")
    out = tmp_path / "found.out"
    result = run("search", "museum", "--engine", "like", "--export", str(out), "--format", "html")
    assert result.exit_code == 0, result.output
    text = out.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>") and "<mark>" in text
    assert run("search", "museum", "--format", "html").exit_code != 0
