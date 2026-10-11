"""Commands that installed add-ons describe with `CliGroup`."""

from __future__ import annotations

import typer
from typer.testing import CliRunner
from vethuq_cli.addons import build, mount

from vethuq_addon_api import CliCommand, CliGroup, CliParam, CliResult, CliSetting


def group(calls):
    def hello(client, name, shout, times):
        calls.append((name, shout, times))
        text = f"hello {name}" * times
        return CliResult(
            lines=[text.upper() if shout else text], data={"n": name}, ok=name != "bad"
        )

    return CliGroup(
        "demo",
        "Demo commands.",
        commands=(
            CliCommand(
                "hello",
                "Say hello.",
                hello,
                (
                    CliParam("name", "Who.", required=True),
                    CliParam("shout", "Loud.", kind="bool"),
                    CliParam("times", "How often.", kind="int", option=True, default=1),
                ),
            ),
            CliCommand("plain", "Return a string.", lambda client: "plain text"),
            CliCommand(
                "rows",
                "Return a table.",
                lambda client: CliResult(table=(["a", "b"], [(1, 2), (3, 4)])),
            ),
        ),
        groups=(
            CliGroup("deep", "Nested.", commands=(CliCommand("x", "X.", lambda c: "nested"),)),
        ),
        settings=(CliSetting("level", "A level.", lambda c: "1", lambda c, v: None),),
    )


def invoke(args, calls=None):
    app = typer.Typer()

    @app.command("keep")
    def keep() -> None: ...

    mount(app, [("demo", group(calls if calls is not None else []))])
    return CliRunner().invoke(app, args)


def test_a_command_gets_its_parameters_by_name():
    calls = []
    result = invoke(["demo", "hello", "Ada", "--shout", "--times", "2"], calls)
    assert calls == [("Ada", True, 2)] and "HELLO ADAHELLO ADA" in result.output


def test_a_string_and_a_table_are_shown():
    assert "plain text" in invoke(["demo", "plain"]).output
    out = invoke(["demo", "rows"]).output
    assert "1" in out and "4" in out


def test_nested_groups_are_mounted():
    assert "nested" in invoke(["demo", "deep", "x"]).output


def test_a_failed_result_exits_non_zero():
    assert invoke(["demo", "hello", "bad"]).exit_code == 1


def test_a_group_that_clashes_with_a_builtin_is_skipped():
    app = typer.Typer()
    app.command("demo")(lambda: None)
    mount(app, [("demo", group([]))])
    assert not app.registered_groups


def test_build_returns_a_typer_app():
    assert isinstance(build(group([])), typer.Typer)
