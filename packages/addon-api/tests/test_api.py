from __future__ import annotations

import json

import pytest

from vethuq_addon_api import (
    API_VERSION,
    Addon,
    AddonError,
    Hook,
    Host,
    LanguageSpec,
    Manifest,
    MigrationInfo,
)
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
        assert manifest.to_dict()["addon_api"] == {"min": API_VERSION, "max": API_VERSION}
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


class TestLanguages:
    def test_an_addon_provides_no_languages_by_default(self, tmp_path):
        class Plain(Addon):
            manifest = Manifest("plain", "Plain", "1.0.0")

        assert Plain(FakeHost(tmp_path / "v.db")).languages() == []

    def test_a_language_addon_returns_specs(self, tmp_path):
        class English(Addon):
            manifest = Manifest("english", "English", "1.0.0")

            def languages(self):
                return [LanguageSpec("en", "English", script="latin", default=True)]

        (spec,) = English(FakeHost(tmp_path / "v.db")).languages()
        assert spec.id == "en" and spec.default and spec.available

    def test_spec_defaults_and_display_label(self):
        spec = LanguageSpec("te", "Telugu", native_label="తెలుగు")
        assert (spec.default, spec.available, spec.reason, dict(spec.ocr)) == (False, True, "", {})
        assert spec.display_label == "Telugu (తెలుగు)"
        assert LanguageSpec("en", "English").display_label == "English"

    def test_serialising(self):
        import json

        spec = LanguageSpec("en", "English", ocr={"engine": {"paddle": {"lang": "en"}}})
        assert spec.to_dict()["ocr"] == {"engine": {"paddle": {"lang": "en"}}}
        assert json.loads(spec.to_json())["id"] == "en"

    def test_is_frozen(self):
        with pytest.raises(AttributeError):
            LanguageSpec("en", "English").id = "x"
