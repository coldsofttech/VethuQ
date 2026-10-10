from __future__ import annotations

import json

import pytest

from vethuq_addon_api import API_VERSION, Addon, AddonError, Hook, Host, Manifest, MigrationInfo
from vethuq_addon_api.testing import FakeHost


class TestManifest:
    def test_supports_the_current_api(self):
        assert Manifest("x", "X", "1.0.0").supports(API_VERSION)

    @pytest.mark.parametrize(
        "api_min,api_max,api,expected",
        [
            ("0.1.0", "0.3.0", "0.2.0", True),
            ("0.2.0", "0.3.0", "0.1.0", False),
            ("0.1.0", "0.1.0", "0.2.0", False),
            ("0.1", "0.1", "0.1.0", True),
            ("0.1.0", "0.1.9", "0.1.5", True),
        ],
    )
    def test_range(self, api_min, api_max, api, expected):
        assert Manifest("x", "X", "1", api_min, api_max).supports(api) is expected

    def test_garbage_range_is_unsupported(self):
        assert not Manifest("x", "X", "1", "a", "b").supports("0.1")

    def test_to_dict_and_json(self):
        manifest = Manifest("backup", "Backup", "0.1.0")
        assert manifest.to_dict()["addon_api"] == {"min": "0.1.0", "max": "0.1.0"}
        assert json.loads(manifest.to_json())["id"] == "backup"


class TestHost:
    def test_fake_host_satisfies_the_protocol(self, tmp_path):
        assert isinstance(FakeHost(tmp_path / "v.db"), Host)

    def test_settings_roundtrip(self, tmp_path):
        host = FakeHost(tmp_path / "v.db")
        assert host.get_setting("a", "d") == "d"
        host.set_setting("a", "1")
        assert host.get_setting("a") == "1"
        host.reset_setting("a")
        assert host.get_setting("a") is None

    def test_release_and_log_are_recorded(self, tmp_path):
        host = FakeHost(tmp_path / "v.db")
        host.release_database()
        host.log(20, "hello")
        assert host.released == 1
        assert host.logs == [(20, "hello")]


class TestAddon:
    def test_hooks_default_to_no_ops(self, tmp_path):
        class Plain(Addon):
            manifest = Manifest("plain", "Plain", "1.0.0")

        addon = Plain(FakeHost(tmp_path / "v.db"))
        addon.on_open()
        addon.before_migration(MigrationInfo(tmp_path / "v.db", 1, 2))

    def test_hook_names(self):
        assert {hook.value for hook in Hook} == {"on_open", "before_migration"}


class TestErrors:
    def test_message_and_hint(self):
        error = AddonError("It broke.", "Try again.")
        assert str(error) == "It broke. Try again."
        assert error.hint == "Try again."
