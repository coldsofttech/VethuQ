"""The search settings as editable fields, shared by the single-setting windows and the full
Search settings window."""

from __future__ import annotations

from vethuq_core.settings import SearchSettings
from vethuq_core.storage import Storage

from vethuq_ui.windows.settings.fields import ChoiceField, NumberField


class SearchFields:
    """Builds each field for one open window (a field holds that window's Tk variables)."""

    SNIPPET_MAX = 500
    SNIPPET_STEP = 10

    @staticmethod
    def snippet(storage: Storage) -> NumberField:
        return NumberField(
            storage,
            "Snippet",
            "Characters of context shown on each side of a match. 0 shows only the match.",
            "Search snippet",
            str(SearchSettings.DEFAULT_SNIPPET_CONTEXT_CHARS),
            SearchSettings.get_snippet_context_chars,
            lambda s, v: SearchSettings.set_snippet_context_chars(s, int(v)),
            SearchSettings.reset_snippet_context_chars,
            minimum=0,
            maximum=SearchFields.SNIPPET_MAX,
            step=SearchFields.SNIPPET_STEP,
        )

    @staticmethod
    def export_format(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Export format",
            "The format an export is written in when none is chosen.",
            "Export format",
            SearchSettings.DEFAULT_EXPORT_FORMAT,
            SearchSettings.get_export_format,
            SearchSettings.set_export_format,
            SearchSettings.reset_export_format,
            choices=[(value, value.upper()) for value in SearchSettings.EXPORT_FORMATS],
        )

    @staticmethod
    def engine(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Engine",
            "The search engine used when none is chosen. 'all' runs every engine and ranks "
            "the pages together.",
            "Search engine",
            SearchSettings.DEFAULT_ENGINE,
            SearchSettings.get_engine,
            SearchSettings.set_engine,
            SearchSettings.reset_engine,
            choices=[(value, value) for value in SearchSettings.ENGINES],
            columns=4,
        )

    @staticmethod
    def fuzzy_threshold(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Fuzzy threshold",
            "How close a word must be to your query for the fuzzy engine to match it.",
            "Fuzzy threshold",
            SearchSettings.DEFAULT_FUZZY_THRESHOLD,
            SearchSettings.get_fuzzy_threshold_setting,
            SearchSettings.set_fuzzy_threshold,
            SearchSettings.reset_fuzzy_threshold,
            choices=[(name, name) for name in SearchSettings.FUZZY_PRESETS],
            custom_label="Custom (% or 0-1)",
        )

    @staticmethod
    def proximity_distance(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Proximity distance",
            "Most words allowed between your first and last word for the proximity engine.",
            "Proximity distance",
            SearchSettings.DEFAULT_PROXIMITY_DISTANCE,
            SearchSettings.get_proximity_distance_setting,
            SearchSettings.set_proximity_distance,
            SearchSettings.reset_proximity_distance,
            choices=[(name, name) for name in SearchSettings.PROXIMITY_PRESETS],
            custom_label=f"Custom (1-{SearchSettings.PROXIMITY_MAX_DISTANCE} words)",
        )

    @staticmethod
    def noise(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Noise level",
            "How much stray punctuation and whitespace the noise-fuzzy engine skips.",
            "Noise level",
            SearchSettings.DEFAULT_NOISE,
            SearchSettings.get_noise_level,
            SearchSettings.set_noise_level,
            SearchSettings.reset_noise_level,
            choices=[(name, name) for name in SearchSettings.NOISE_LEVELS],
        )

    @staticmethod
    def case(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Case",
            "Whether upper and lower case are the same. 'auto' uses each engine's own default.",
            "Case handling",
            SearchSettings.NORMALIZE_AUTO,
            SearchSettings.get_case,
            SearchSettings.set_case,
            SearchSettings.reset_case,
            choices=[(value, value) for value in SearchSettings.CASE_VALUES],
        )

    @staticmethod
    def leetspeak(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Leetspeak",
            "Whether look-alike characters (3 for e, @ for a) count as the letters.",
            "Leetspeak handling",
            SearchSettings.NORMALIZE_AUTO,
            SearchSettings.get_leetspeak,
            SearchSettings.set_leetspeak,
            SearchSettings.reset_leetspeak,
            choices=[(value, value) for value in SearchSettings.LEETSPEAK_VALUES],
            columns=5,
        )

    @staticmethod
    def unicode(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Unicode",
            "Whether characters written differently count as the same (café, cafe).",
            "Unicode handling",
            SearchSettings.NORMALIZE_AUTO,
            SearchSettings.get_unicode,
            SearchSettings.set_unicode,
            SearchSettings.reset_unicode,
            choices=[(value, value) for value in SearchSettings.UNICODE_VALUES],
            columns=4,
        )
