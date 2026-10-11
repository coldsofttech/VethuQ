"""Add-ons that add commands to the `vethuq` command line."""

from __future__ import annotations

import sys

import pytest

import tests.fake_pipeline as fp
import vethuq
from vethuq_addon_api import Addon, CliCommand, CliGroup, Manifest


class FakeCliAddon(Addon):
    manifest = Manifest(id="clidemo", name="vethuq-addon-clidemo", version="0.1.0")

    def cli(self):
        return CliGroup("clidemo", "Demo.", commands=(CliCommand("hi", "Say hi.", lambda c: "hi"),))


class BrokenCliAddon(Addon):
    manifest = Manifest(id="clibroken", name="vethuq-addon-clibroken", version="0.1.0")

    def cli(self):
        raise RuntimeError("boom")


fp.FakeCliAddon = FakeCliAddon
fp.BrokenCliAddon = BrokenCliAddon


@pytest.fixture
def client(tmp_path_factory, monkeypatch, tmp_path):
    folder = tmp_path_factory.mktemp("cli_addons")
    monkeypatch.setattr(sys, "path", [str(folder), *sys.path])
    fp.install(
        folder,
        {
            "clidemo": ("vethuq_addon_clidemo", "FakeCliAddon"),
            "clibroken": ("vethuq_addon_clibroken", "BrokenCliAddon"),
        },
    )
    with vethuq.VethuQ(db_path=tmp_path / "db" / "vethuq.db") as client:
        yield client


def test_the_groups_of_running_addons_are_listed_and_a_broken_one_is_skipped(client):
    groups = dict(client.addons.cli())
    assert groups["clidemo"].name == "clidemo" and "clibroken" not in groups
    assert groups["clidemo"].commands[0].run(client) == "hi"
