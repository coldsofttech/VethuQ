from __future__ import annotations

from scripts.dev.sync import Sync


def test_syncs_every_package_and_the_dev_group():
    assert Sync.COMMAND == ("uv", "sync", "--all-packages", "--group", "dev")
