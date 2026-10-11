"""The command-line description an add-on can return."""

from __future__ import annotations

from types import SimpleNamespace

from vethuq_addon_api import Addon, CliGroup, CliResult, Manifest, licence_commands
from vethuq_addon_api.testing import FakeHost


def test_an_addon_adds_no_commands_by_default(tmp_path):
    class Plain(Addon):
        manifest = Manifest("plain", "plain", "1.0.0")

    assert Plain(FakeHost(tmp_path / "db")).cli() is None


class FakeLicensed:
    def __init__(self, client):
        self.client = client

    def licence(self):
        return SimpleNamespace(ok=self.client.valid, status=SimpleNamespace(value="active"))

    def set_licence(self, token):
        self.client.token = token
        return self.licence()

    def remove_licence(self):
        self.client.token = None


def test_licence_commands_show_set_and_remove():
    group = licence_commands(FakeLicensed, "Fake")
    assert isinstance(group, CliGroup) and group.name == "licence"
    by_name = {c.name: c for c in group.commands}
    client = SimpleNamespace(valid=True, token=None)
    shown = by_name["show"].run(client)
    assert (
        isinstance(shown, CliResult)
        and shown.ok
        and shown.data
        == {
            "licensed": True,
            "status": "active",
        }
    )
    assert by_name["set"].params[0].required
    by_name["set"].run(client, token="abc")
    assert client.token == "abc"
    assert by_name["remove"].run(client) == "Fake: licence removed." and client.token is None
    assert not by_name["show"].run(SimpleNamespace(valid=False)).ok
