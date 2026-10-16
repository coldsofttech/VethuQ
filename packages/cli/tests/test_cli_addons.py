"""Commands that installed add-ons describe with `CliGroup`."""

from __future__ import annotations

from types import SimpleNamespace

import typer
from typer.testing import CliRunner
from vethuq_cli.addons import build, mount, mount_stopped
from vethuq_cli.settings import addon_app

from vethuq.enums import AddonStatus
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


def info(addon_id, status, detail="", disabled=False):
    return SimpleNamespace(
        id=addon_id,
        name=f"vethuq-addon-{addon_id}",
        status=status,
        detail=detail,
        disabled=disabled,
    )


STOPPED = [
    info("off", AddonStatus.DISABLED, "turned off in settings", disabled=True),
    info("odd", AddonStatus.INCOMPATIBLE, "built for Windows; VethuQ is running on Linux"),
    info("bad", AddonStatus.FAILED, "No module named 'x'"),
    info("fine", AddonStatus.LOADED),
]


def stopped_app():
    app = typer.Typer()

    @app.command("keep")
    def keep() -> None: ...

    mount_stopped(app, STOPPED)
    return app


def test_a_stopped_addon_is_listed_and_explains_itself():
    runner = CliRunner()
    listing = runner.invoke(stopped_app(), ["--help"]).output
    assert "off" in listing and "odd" in listing and "bad" in listing and "fine" not in listing
    for name, hint in (
        ("off", "vethuq addons enable off"),
        ("odd", "built for Windows"),
        ("bad", "No module named"),
    ):
        result = runner.invoke(stopped_app(), [name, "licence", "show"])
        assert result.exit_code == 1 and "isn't running" in result.output and hint in result.output


def test_a_stopped_addon_never_replaces_a_builtin():
    app = typer.Typer()
    app.command("off")(lambda: None)
    mount_stopped(app, STOPPED)
    assert [c.name for c in app.registered_commands].count("off") == 1
    assert "(not running" not in (app.registered_commands[0].help or "")


def settings_client(groups, infos):
    return SimpleNamespace(addons=SimpleNamespace(cli=lambda: groups, list=lambda: infos))


def test_settings_of_a_stopped_addon_say_why():
    app = typer.Typer()
    app.add_typer(addon_app(settings_client([("demo", group([]))], STOPPED)), name="addons")
    runner = CliRunner()
    shown = runner.invoke(app, ["addons", "demo", "level"])
    assert shown.exit_code == 0 and "level: 1" in shown.output
    result = runner.invoke(app, ["addons", "off"])
    assert result.exit_code == 1 and "settings aren't available" in result.output


def test_a_setting_that_refuses_gives_a_message_not_a_traceback():
    def refuse(client):
        raise PermissionError("Word files need a licence")

    locked = CliGroup(
        "locked", "Locked.", settings=(CliSetting("mode", "A mode.", refuse, lambda c, v: None),)
    )
    app = typer.Typer()
    app.add_typer(addon_app(settings_client([("locked", locked)], [])), name="addons")
    result = CliRunner().invoke(app, ["addons", "locked", "mode"])
    assert result.exit_code != 0 and "Unavailable: Word files need a licence" in result.output
