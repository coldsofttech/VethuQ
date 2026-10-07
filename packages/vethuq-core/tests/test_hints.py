import pytest
from vethuq_core.hints import Hints


@pytest.fixture(autouse=True)
def _terminal():
    Hints.interactive = False
    yield
    Hints.interactive = False


class TestInTheTerminal:
    @pytest.mark.parametrize(
        "command",
        ["index status", "vethuq index status", "db restore <name>", "index run --lang te"],
    )
    def test_names_the_command_as_typed(self, command):
        typed = command if command.startswith("vethuq") else f"vethuq {command}"

        assert Hints.command(command) == typed

    def test_backticks_and_quotes_are_not_part_of_it(self):
        assert Hints.command("`vethuq index run`") == "vethuq index run"


class TestInTheInteractiveShell:
    @pytest.fixture(autouse=True)
    def _interactive(self):
        Hints.interactive = True

    @pytest.mark.parametrize(
        ("command", "menu"),
        [
            ("index status", "Index > Status"),
            ("vethuq index run", "Index > Run"),
            ("index run --lang te", "Index > Run"),
            ("db restore <name>", "Db > Restore"),
            ("db backup list", "Db > Backup > List"),
            ("source list <source>", "Sources > List Files"),
            ("source list", "Sources > List"),
            ("source add <path>", "Sources > Add"),
            ("index reindex file <id>", "Index > Reindex file"),
            ("index reindex <source>", "Index > Reindex source"),
            ("settings search noise-fuzzy noise", "Settings > Search > Noise Level"),
            (
                "settings search semantic combine full-text",
                "Settings > Search > Semantic > Combine",
            ),
            ("settings location backups set", "Settings > Location > Backups"),
            ("settings index stale-lock set enable", "Settings > Index > Stale Lock"),
            ("logs <component> --tail 40", "Logs"),
            ("file-types list", "File types & search engines > File types"),
        ],
    )
    def test_names_the_menu_instead(self, command, menu):
        assert Hints.command(command) == menu
        assert "vethuq" not in Hints.command(command)

    def test_a_command_with_no_menu_says_it_is_for_a_terminal(self):
        assert (
            Hints.command("background-service install")
            == "vethuq background-service install (in a terminal)"
        )
