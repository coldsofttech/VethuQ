from __future__ import annotations


def test_a_setting_is_shown_set_shown_and_reset(run):
    assert "workers: auto" in run("settings", "index", "workers").output
    assert "workers: 3" in run("settings", "index", "workers", "3").output
    assert "workers: 3" in run("settings", "index", "workers").output
    assert "workers: auto" in run("settings", "index", "workers", "--reset").output


def test_values_keep_their_type(run):
    assert "gpu: yes" in run("settings", "ocr", "gpu", "true").output
    assert (
        "snippet-context-chars: 120"
        in run("settings", "search", "snippet-context-chars", "120").output
    )


def test_a_refused_value_is_an_error(run):
    assert run("settings", "index", "stale-lock", "sometimes").exit_code != 0


def test_search_normalizers_are_a_level_of_the_hierarchy(run):
    assert "case: ignore" in run("settings", "search", "normalize", "case", "ignore").output
    assert "case: auto" in run("settings", "search", "normalize", "case", "--reset").output


def test_engine_options_are_a_sub_hierarchy(run):
    assert "threshold" in run("settings", "search", "fuzzy").output
    assert "threshold: loose" in run("settings", "search", "fuzzy", "threshold", "loose").output
    assert (
        "threshold: balanced" in run("settings", "search", "fuzzy", "threshold", "--reset").output
    )
    assert "noise" in run("settings", "search", "noise-fuzzy").output


def test_show_lists_every_setting(run, run_json):
    rows = run_json("settings", "show")
    names = {r["setting"] for r in rows}
    assert {"index workers", "ocr gpu", "search engine"} <= names


def test_json_output(run_json):
    assert run_json("settings", "index", "workers") == {"workers": "auto"}
