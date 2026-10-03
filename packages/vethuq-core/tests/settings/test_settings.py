import pytest
from vethuq_core.settings import (
    DbSettings,
    GpuSettings,
    IndexSettings,
    InvalidSettingValueError,
    SearchSettings,
    Settings,
)
from vethuq_core.storage import Storage


class TestSettings:
    def test_set_setting_overwrites_existing_value(self, storage: Storage):
        Settings.set(storage, "key", "first")
        Settings.set(storage, "key", "second")

        assert Settings.get(storage, "key") == "second"

    def test_get_setting_missing_key_returns_none(self, storage: Storage):
        assert Settings.get(storage, "does-not-exist") is None


class TestGpuSettings:
    def test_gpu_disabled_by_default(self, storage: Storage):
        assert GpuSettings.is_enabled(storage) is False

    def test_set_gpu_enabled_roundtrip(self, storage: Storage):
        GpuSettings.set_enabled(storage, True)
        assert GpuSettings.is_enabled(storage) is True

        GpuSettings.set_enabled(storage, False)
        assert GpuSettings.is_enabled(storage) is False


class TestSearchSettings:
    def test_resolve_export_format_uses_given_value_else_the_default(self, storage: Storage):
        assert SearchSettings.resolve_export_format(storage, "html") == "html"
        assert SearchSettings.resolve_export_format(storage) == "json"
        SearchSettings.set_export_format(storage, "html")
        assert SearchSettings.resolve_export_format(storage) == "html"

    def test_resolve_export_format_rejects_unsupported_format(self, storage: Storage):
        with pytest.raises(InvalidSettingValueError, match="unsupported export format 'xml'"):
            SearchSettings.resolve_export_format(storage, "xml")

    def test_search_export_format_defaults_to_json(self, storage: Storage):
        assert SearchSettings.get_export_format(storage) == "json"

    def test_set_search_export_format_roundtrip(self, storage: Storage):
        SearchSettings.set_export_format(storage, "html")
        assert SearchSettings.get_export_format(storage) == "html"

    def test_set_search_export_format_rejects_unsupported_format(self, storage: Storage):
        with pytest.raises(ValueError):
            SearchSettings.set_export_format(storage, "xml")

    def test_search_snippet_context_chars_defaults_to_80(self, storage: Storage):
        assert SearchSettings.get_snippet_context_chars(storage) == 80

    def test_set_search_snippet_context_chars_roundtrip(self, storage: Storage):
        SearchSettings.set_snippet_context_chars(storage, 40)
        assert SearchSettings.get_snippet_context_chars(storage) == 40

    def test_set_search_snippet_context_chars_rejects_negative(self, storage: Storage):
        with pytest.raises(ValueError, match="non-negative"):
            SearchSettings.set_snippet_context_chars(storage, -1)

    def test_search_engine_defaults_to_like(self, storage: Storage):
        assert SearchSettings.get_engine(storage) == "like"

    def test_set_search_engine_roundtrip(self, storage: Storage):
        SearchSettings.set_engine(storage, "full-text")
        assert SearchSettings.get_engine(storage) == "full-text"

    def test_set_search_engine_rejects_unknown_engine(self, storage: Storage):
        with pytest.raises(ValueError):
            SearchSettings.set_engine(storage, "nope")

    def test_search_case_sensitive_defaults_to_disabled_and_roundtrips(self, storage: Storage):
        assert SearchSettings.is_case_sensitive(storage) is False
        SearchSettings.set_case_sensitive(storage, True)
        assert SearchSettings.is_case_sensitive(storage) is True
        SearchSettings.set_case_sensitive(storage, False)
        assert SearchSettings.is_case_sensitive(storage) is False

    def test_fuzzy_threshold_defaults_to_balanced(self, storage: Storage):
        assert SearchSettings.get_fuzzy_threshold_setting(storage) == "balanced"
        assert SearchSettings.get_fuzzy_threshold(storage) == 0.8

    @pytest.mark.parametrize(
        ("value", "ratio"),
        [
            ("strict", 0.9),
            ("balanced", 0.8),
            ("loose", 0.65),
            ("LOOSE", 0.65),
            ("0.75", 0.75),
            ("1", 1.0),
        ],
    )
    def test_set_fuzzy_threshold_roundtrip(self, storage: Storage, value: str, ratio: float):
        SearchSettings.set_fuzzy_threshold(storage, value)

        assert SearchSettings.get_fuzzy_threshold_setting(storage) == value.lower()
        assert SearchSettings.get_fuzzy_threshold(storage) == ratio

    @pytest.mark.parametrize("value", ["", "nope", "0", "-0.5", "1.01", "nan"])
    def test_set_fuzzy_threshold_rejects_invalid_values(self, storage: Storage, value: str):
        with pytest.raises(ValueError):
            SearchSettings.set_fuzzy_threshold(storage, value)
        assert SearchSettings.get_fuzzy_threshold_setting(storage) == "balanced"

    def test_a_corrupt_stored_fuzzy_threshold_falls_back_to_the_default(self, storage: Storage):
        Settings.set(storage, "search_fuzzy_threshold", "garbage")

        assert SearchSettings.get_fuzzy_threshold_setting(storage) == "balanced"
        assert SearchSettings.get_fuzzy_threshold(storage) == 0.8

    def test_parse_fuzzy_threshold_accepts_numbers_and_names(self):
        assert SearchSettings.parse_fuzzy_threshold(0.5) == 0.5
        assert SearchSettings.parse_fuzzy_threshold(" Strict ") == 0.9
        with pytest.raises(ValueError):
            SearchSettings.parse_fuzzy_threshold(0)


class TestIndexSettings:
    def test_thread_workers_defaults_to_disabled(self, storage: Storage):
        assert IndexSettings.get_thread_workers(storage) == "0"

    @pytest.mark.parametrize("value", ["0", "1", "8", "auto"])
    def test_set_thread_workers_roundtrip(self, storage: Storage, value: str):
        IndexSettings.set_thread_workers(storage, value)
        assert IndexSettings.get_thread_workers(storage) == value

    @pytest.mark.parametrize("value", ["-1", "9", "abc", ""])
    def test_set_thread_workers_rejects_out_of_range_value(self, storage: Storage, value: str):
        with pytest.raises(ValueError):
            IndexSettings.set_thread_workers(storage, value)


class TestDbSettings:
    def test_integrity_check_defaults_to_auto(self, storage: Storage):
        assert DbSettings.get_integrity_check(storage) == "auto"

    @pytest.mark.parametrize("value", ["enable", "disable", "auto"])
    def test_set_integrity_check_roundtrip(self, storage: Storage, value: str):
        DbSettings.set_integrity_check(storage, value)
        assert DbSettings.get_integrity_check(storage) == value

    def test_set_integrity_check_rejects_invalid_value(self, storage: Storage):
        with pytest.raises(ValueError):
            DbSettings.set_integrity_check(storage, "sometimes")

    def test_integrity_check_interval_minutes_defaults_to_one_day(self, storage: Storage):
        assert DbSettings.get_integrity_check_interval_minutes(storage) == 24 * 60

    def test_set_integrity_check_interval_minutes_roundtrip(self, storage: Storage):
        DbSettings.set_integrity_check_interval_minutes(storage, 60)
        assert DbSettings.get_integrity_check_interval_minutes(storage) == 60

    def test_set_integrity_check_interval_minutes_rejects_negative(self, storage: Storage):
        with pytest.raises(ValueError, match="non-negative"):
            DbSettings.set_integrity_check_interval_minutes(storage, -1)
