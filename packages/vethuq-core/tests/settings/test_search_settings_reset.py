import pytest
from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage

# (changes the setting, resets it, reads it back, the default)
CASES = {
    "snippet": (
        lambda s: SearchSettings.set_snippet_context_chars(s, 5),
        SearchSettings.reset_snippet_context_chars,
        SearchSettings.get_snippet_context_chars,
        SearchSettings.DEFAULT_SNIPPET_CONTEXT_CHARS,
    ),
    "export-format": (
        lambda s: SearchSettings.set_export_format(s, "html"),
        SearchSettings.reset_export_format,
        SearchSettings.get_export_format,
        SearchSettings.DEFAULT_EXPORT_FORMAT,
    ),
    "engine": (
        lambda s: SearchSettings.set_engine(s, "exact"),
        SearchSettings.reset_engine,
        SearchSettings.get_engine,
        SearchSettings.DEFAULT_ENGINE,
    ),
    "case": (
        lambda s: SearchSettings.set_case(s, "match"),
        SearchSettings.reset_case,
        SearchSettings.get_case,
        SearchSettings.NORMALIZE_AUTO,
    ),
    "fuzzy-threshold": (
        lambda s: SearchSettings.set_fuzzy_threshold(s, "strict"),
        SearchSettings.reset_fuzzy_threshold,
        SearchSettings.get_fuzzy_threshold_setting,
        SearchSettings.DEFAULT_FUZZY_THRESHOLD,
    ),
    "semantic-threshold": (
        lambda s: SearchSettings.set_semantic_threshold(s, "strict"),
        SearchSettings.reset_semantic_threshold,
        SearchSettings.get_semantic_threshold_setting,
        SearchSettings.DEFAULT_SEMANTIC_THRESHOLD,
    ),
    "semantic-limit": (
        lambda s: SearchSettings.set_semantic_limit(s, 5),
        SearchSettings.reset_semantic_limit,
        SearchSettings.get_semantic_limit,
        SearchSettings.DEFAULT_SEMANTIC_LIMIT,
    ),
    "semantic-combine": (
        lambda s: SearchSettings.set_semantic_combine(s, "lexical"),
        SearchSettings.reset_semantic_combine,
        SearchSettings.get_semantic_combine,
        SearchSettings.DEFAULT_SEMANTIC_COMBINE,
    ),
    "proximity-distance": (
        lambda s: SearchSettings.set_proximity_distance(s, "tight"),
        SearchSettings.reset_proximity_distance,
        SearchSettings.get_proximity_distance_setting,
        SearchSettings.DEFAULT_PROXIMITY_DISTANCE,
    ),
    "unicode": (
        lambda s: SearchSettings.set_unicode(s, "full"),
        SearchSettings.reset_unicode,
        SearchSettings.get_unicode,
        SearchSettings.NORMALIZE_AUTO,
    ),
    "leetspeak": (
        lambda s: SearchSettings.set_leetspeak(s, "extended"),
        SearchSettings.reset_leetspeak,
        SearchSettings.get_leetspeak,
        SearchSettings.NORMALIZE_AUTO,
    ),
    "noise": (
        lambda s: SearchSettings.set_noise_level(s, "high"),
        SearchSettings.reset_noise_level,
        SearchSettings.get_noise_level,
        SearchSettings.DEFAULT_NOISE,
    ),
}


class TestSearchSettingsReset:
    @pytest.mark.parametrize("name", CASES)
    def test_reset_restores_the_default(self, storage: Storage, name):
        change, reset, read, default = CASES[name]
        change(storage)
        assert read(storage) != default

        reset(storage)

        assert read(storage) == default
