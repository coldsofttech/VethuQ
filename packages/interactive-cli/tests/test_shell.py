from __future__ import annotations

from vethuq_interactive_cli.shell import BACK, EXIT


def selects(ui):
    return [a for a in ui.asked if a[0] == "select"]


def test_the_main_menu_lists_the_groups_then_version_and_exit(shell):
    ui = shell(EXIT)
    keys = selects(ui)[0][2]
    assert keys[:7] == ["search", "source", "index", "settings", "stats", "db", "logs"]
    assert keys[-2:] == ["version", EXIT]
    assert {"languages", "file-types", "addons"} <= set(keys)


def test_exit_says_goodbye(shell, capsys):
    shell(EXIT)
    assert "Goodbye." in capsys.readouterr().out


def test_ctrl_c_leaves_from_anywhere(shell, capsys):
    shell("source")  # the script then runs out, which is Ctrl-C
    assert "Goodbye." in capsys.readouterr().out


def test_a_group_is_a_menu_with_back(shell):
    ui = shell("source", BACK, EXIT)
    assert BACK in selects(ui)[1][2] and "add" in selects(ui)[1][2]


def test_a_command_without_parameters_just_runs(shell, capsys):
    shell("source", "list", BACK, EXIT)
    assert "vethuq source add" in capsys.readouterr().out


def test_a_required_argument_is_asked_until_given(shell, docs, capsys):
    ui = shell("source", "add", "", str(docs), False, BACK, EXIT)
    out = capsys.readouterr().out
    assert "required" in out and "Added source 1" in out
    assert [a for a in ui.asked if a[0] == "text"][0][1].startswith("path")


def test_optional_options_are_asked_only_on_request(shell, docs, capsys):
    shell("source", "add", str(docs), True, "en", BACK, EXIT)
    assert "Added source 1" in capsys.readouterr().out


def test_a_bad_value_is_refused_and_asked_again(shell, capsys):
    shell("index", "history", True, "many", "5", BACK, EXIT)
    assert "not a valid" in capsys.readouterr().out.lower()


def test_a_failing_command_prints_the_error_and_the_shell_goes_on(shell, capsys):
    ui = shell("source", "remove", "99", BACK, EXIT)
    captured = capsys.readouterr()
    assert "Error:" in captured.err
    assert len(selects(ui)) == 4  # main, sources, sources again after the error, main


def test_the_settings_hierarchy_is_nested_menus(shell, capsys):
    ui = shell(
        "settings", "search", "fuzzy", "threshold", "loose", False, BACK, BACK, BACK, BACK, EXIT
    )
    out = capsys.readouterr().out
    assert "threshold: loose" in out
    titles = [a[1] for a in selects(ui)]
    assert any("Settings" in t for t in titles) and any("fuzzy" in t for t in titles)


def test_version_runs_from_the_main_menu(shell, capsys):
    shell("version", EXIT)
    assert "VethuQ" in capsys.readouterr().out
