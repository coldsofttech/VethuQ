from __future__ import annotations

from vethuq_interactive_cli.shell import EXIT


def index(docs, shell):
    shell("source", "add", str(docs), False, "\x00back", EXIT)
    shell("index", "run", "", False, "\x00back", EXIT)


def test_a_guided_search_finds_a_match(shell, docs, capsys):
    index(docs, shell)
    capsys.readouterr()
    ui = shell("search", "museum", "like", False, "", EXIT)
    out = capsys.readouterr().out
    assert "1 match" in out and "hello museum world" in out
    kinds = [a[0] for a in ui.asked]
    assert kinds[:5] == ["select", "text", "select", "confirm", "text"]


def test_the_engines_offered_are_the_installed_ones(shell):
    ui = shell("search", "x")
    engines = [a for a in ui.asked if a[0] == "select" and a[1] == "Engine"][0][2]
    assert {"", "all", "hybrid", "like", "exact", "fuzzy"} <= set(engines)


def test_engine_options_are_asked_and_passed_on(shell, docs, capsys):
    index(docs, shell)
    capsys.readouterr()
    ui = shell("search", "museum", "fuzzy", "loose", False, "", EXIT)
    prompts = [a[1] for a in ui.asked if a[0] == "text"]
    assert any("fuzzy threshold" in p for p in prompts)
    assert "match" in capsys.readouterr().out


def test_an_empty_query_is_asked_again(shell):
    ui = shell("search", "", "museum")
    assert [a[1] for a in ui.asked if a[0] == "text"][:2] == ["Search for", "Search for"]
