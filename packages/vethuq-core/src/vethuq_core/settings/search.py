"""Settings for `search` and its result export."""

from __future__ import annotations

from vethuq_core.settings.settings import InvalidSettingValueError, Settings
from vethuq_core.storage import Storage


class SearchSettings:
    SNIPPET_CONTEXT_CHARS_KEY = "search_snippet_context_chars"
    DEFAULT_SNIPPET_CONTEXT_CHARS = 80
    EXPORT_FORMAT_KEY = "search_export_format"
    DEFAULT_EXPORT_FORMAT = "json"
    EXPORT_FORMATS = ("json", "html")
    ENGINE_KEY = "search_engine"
    DEFAULT_ENGINE = "all"
    ENGINE_ALL = "all"  # not an engine: runs every engine and ranks the pages together
    ENGINES = (
        ENGINE_ALL,
        "like",
        "lexical",
        "exact",
        "full-text",
        "fuzzy",
        "proximity",
        "noise-fuzzy",
    )
    CASE_SENSITIVE_KEY = "search_case_sensitive"
    FUZZY_THRESHOLD_KEY = "search_fuzzy_threshold"
    DEFAULT_FUZZY_THRESHOLD = "balanced"
    # Minimum similarity (0-1] between a query word and a page word for the `fuzzy`
    # engine to count it as a match, by name.
    FUZZY_PRESETS = {"strict": 0.90, "balanced": 0.80, "loose": 0.65}
    PROXIMITY_DISTANCE_KEY = "search_proximity_distance"
    DEFAULT_PROXIMITY_DISTANCE = "medium"
    # Most words the `proximity` engine lets sit between its first and last term, by name.
    PROXIMITY_PRESETS = {"tight": 3, "medium": 10, "loose": 30}
    PROXIMITY_MAX_DISTANCE = 100
    LEETSPEAK_LEVELS = ("basic", "standard", "extended")
    # The normalizers (see `vethuq_core.search.normalizers`): what counts as the same character.
    # Each setting is `auto` (every engine's own default) or a value that applies to every
    # engine that can honour it.
    NORMALIZE_AUTO = "auto"
    NORMALIZE_CASE_KEY = "search_normalize_case"
    CASE_VALUES = (NORMALIZE_AUTO, "ignore", "match")
    NORMALIZE_LEETSPEAK_KEY = "search_normalize_leetspeak"
    LEETSPEAK_OFF = "off"
    LEETSPEAK_VALUES = (NORMALIZE_AUTO, LEETSPEAK_OFF, *LEETSPEAK_LEVELS)
    # What `auto` is for the engines that look through look-alikes unless told not to, and for
    # the combined search (whose look-alike results come from it).
    DEFAULT_LEETSPEAK = "basic"
    LEGACY_LEETSPEAK_KEY = "search_leetspeak_level"  # before it was a normalizer
    NORMALIZE_UNICODE_KEY = "search_normalize_unicode"
    UNICODE_LEVELS = ("off", "basic", "full")  # nothing, NFC, NFKC with accents folded
    UNICODE_VALUES = (NORMALIZE_AUTO, *UNICODE_LEVELS)
    # What `auto` is for each engine that takes a Unicode level: `exact` and `like` compose
    # characters (NFC), the fuzzy engines also fold accents.
    UNICODE_DEFAULTS = {"exact": "basic", "like": "basic", "fuzzy": "full", "noise-fuzzy": "full"}
    NOISE_KEY = "search_noise_level"
    DEFAULT_NOISE = "low"
    # How much stray punctuation and whitespace the `noise-fuzzy` engine skips inside a match,
    # by name: (most in a row between two characters, most in the whole match).
    NOISE_LEVELS = {"low": (1, 2), "medium": (3, 6), "high": (6, 12)}

    @staticmethod
    def get_snippet_context_chars(storage: Storage) -> int:
        """How many characters of context `search` shows around a match. 80 by default."""
        value = Settings.get(storage, SearchSettings.SNIPPET_CONTEXT_CHARS_KEY)
        return int(value) if value is not None else SearchSettings.DEFAULT_SNIPPET_CONTEXT_CHARS

    @staticmethod
    def set_snippet_context_chars(storage: Storage, chars: int) -> None:
        if chars < 0:
            raise InvalidSettingValueError("chars must be non-negative")
        Settings.set(storage, SearchSettings.SNIPPET_CONTEXT_CHARS_KEY, str(chars))

    @staticmethod
    def reset_snippet_context_chars(storage: Storage) -> None:
        """Back to the default snippet context."""
        SearchSettings.set_snippet_context_chars(
            storage, SearchSettings.DEFAULT_SNIPPET_CONTEXT_CHARS
        )

    @staticmethod
    def get_export_format(storage: Storage) -> str:
        """Default format `search --export` writes to when none is given. 'json' by default."""
        value = Settings.get(storage, SearchSettings.EXPORT_FORMAT_KEY)
        return value if value is not None else SearchSettings.DEFAULT_EXPORT_FORMAT

    @staticmethod
    def resolve_export_format(storage: Storage, format_: str | None = None) -> str:
        """`format_` if given (validated), else the configured default export format.

        Raises `InvalidSettingValueError` for a format that isn't supported.
        """
        resolved = format_ if format_ is not None else SearchSettings.get_export_format(storage)
        if resolved not in SearchSettings.EXPORT_FORMATS:
            raise InvalidSettingValueError(
                f"unsupported export format '{resolved}'. "
                f"Use one of: {', '.join(SearchSettings.EXPORT_FORMATS)}."
            )
        return resolved

    @staticmethod
    def set_export_format(storage: Storage, format_: str) -> None:
        if format_ not in SearchSettings.EXPORT_FORMATS:
            raise InvalidSettingValueError(f"format must be one of {SearchSettings.EXPORT_FORMATS}")
        Settings.set(storage, SearchSettings.EXPORT_FORMAT_KEY, format_)

    @staticmethod
    def reset_export_format(storage: Storage) -> None:
        """Back to the default export format."""
        SearchSettings.set_export_format(storage, SearchSettings.DEFAULT_EXPORT_FORMAT)

    @staticmethod
    def get_engine(storage: Storage) -> str:
        """Default engine `search` uses when none is given. 'all' (every engine) by default."""
        value = Settings.get(storage, SearchSettings.ENGINE_KEY)
        return value if value in SearchSettings.ENGINES else SearchSettings.DEFAULT_ENGINE

    @staticmethod
    def set_engine(storage: Storage, engine: str) -> None:
        if engine not in SearchSettings.ENGINES:
            raise InvalidSettingValueError(f"engine must be one of {SearchSettings.ENGINES}")
        Settings.set(storage, SearchSettings.ENGINE_KEY, engine)

    @staticmethod
    def reset_engine(storage: Storage) -> None:
        """Back to the default search engine."""
        SearchSettings.set_engine(storage, SearchSettings.DEFAULT_ENGINE)

    @staticmethod
    def parse_case(value: str, *, allow_auto: bool = False) -> str:
        """Resolve a case setting: `ignore`, `match` or (when stored) `auto`.

        Raises `InvalidSettingValueError` for anything else.
        """
        text = value.strip().lower() if isinstance(value, str) else ""
        allowed = SearchSettings.CASE_VALUES if allow_auto else SearchSettings.CASE_VALUES[1:]
        if text not in allowed:
            raise InvalidSettingValueError(f"case must be one of {', '.join(allowed)}")
        return text

    @staticmethod
    def get_case(storage: Storage) -> str:
        """The stored case setting: `ignore`, `match` or `auto` (each engine's own default).

        A database that only has the older on/off setting reads it as `match` / `ignore`.
        """
        value = Settings.get(storage, SearchSettings.NORMALIZE_CASE_KEY)
        if value is not None:
            try:
                return SearchSettings.parse_case(value, allow_auto=True)
            except InvalidSettingValueError:
                return SearchSettings.NORMALIZE_AUTO
        legacy = Settings.get(storage, SearchSettings.CASE_SENSITIVE_KEY)
        if legacy in ("true", "false"):
            return "match" if legacy == "true" else "ignore"
        return SearchSettings.NORMALIZE_AUTO

    @staticmethod
    def set_case(storage: Storage, value: str) -> None:
        """Store the case setting: `auto`, `ignore` or `match`."""
        Settings.set(
            storage,
            SearchSettings.NORMALIZE_CASE_KEY,
            SearchSettings.parse_case(value, allow_auto=True),
        )

    @staticmethod
    def is_case_sensitive(storage: Storage) -> bool:
        """Whether `search` matches case by default: only if the case setting is `match`.

        Acted on by the `like`, `lexical`, `fuzzy` and `noise-fuzzy` engines: `exact` is always
        case-sensitive and `full-text` and `proximity` never are.
        """
        return SearchSettings.get_case(storage) == "match"

    @staticmethod
    def set_case_sensitive(storage: Storage, enabled: bool) -> None:
        SearchSettings.set_case(storage, "match" if enabled else "ignore")

    @staticmethod
    def reset_case(storage: Storage) -> None:
        """Back to `auto`: each engine's own case handling."""
        SearchSettings.set_case(storage, SearchSettings.NORMALIZE_AUTO)

    @staticmethod
    def parse_fuzzy_threshold(value: str | float) -> float:
        """Resolve a fuzzy threshold to a similarity in (0, 1].

        `value` is a preset name (`strict`, `balanced`, `loose`), a percentage
        (`"80%"`, or a whole number above 1 such as `80`), or a similarity
        (`0.8`, `1`). Raises `InvalidSettingValueError` for anything else.
        """
        invalid = InvalidSettingValueError(
            f"threshold must be one of {tuple(SearchSettings.FUZZY_PRESETS)}, a percentage "
            "above 0 and up to 100 (e.g. 80%), or a similarity above 0 and up to 1 (e.g. 0.8)"
        )
        if isinstance(value, str):
            text = value.strip().lower()
            preset = SearchSettings.FUZZY_PRESETS.get(text)
            if preset is not None:
                return preset
            percent = text.endswith("%")
            try:
                number = float(text.removesuffix("%"))
            except ValueError:
                raise invalid from None
        else:
            percent = False
            number = float(value)
        if not number == number:  # NaN
            raise invalid
        if percent:
            number /= 100
        elif number > 1:
            # A plain number above 1 is only meaningful as a whole percentage ("80").
            if number != int(number) or number > 100:
                raise invalid
            number /= 100
        if not 0 < number <= 1:
            raise invalid
        return number

    @staticmethod
    def get_fuzzy_threshold_setting(storage: Storage) -> str:
        """The stored fuzzy threshold as set - a preset name or a number. 'balanced' by default."""
        value = Settings.get(storage, SearchSettings.FUZZY_THRESHOLD_KEY)
        if value is None:
            return SearchSettings.DEFAULT_FUZZY_THRESHOLD
        try:
            SearchSettings.parse_fuzzy_threshold(value)
        except InvalidSettingValueError:
            return SearchSettings.DEFAULT_FUZZY_THRESHOLD
        return value

    @staticmethod
    def get_fuzzy_threshold(storage: Storage) -> float:
        """Minimum word similarity the `fuzzy` engine accepts by default (0.80 is 'balanced')."""
        return SearchSettings.parse_fuzzy_threshold(
            SearchSettings.get_fuzzy_threshold_setting(storage)
        )

    @staticmethod
    def set_fuzzy_threshold(storage: Storage, value: str) -> None:
        """Store the default fuzzy threshold: a preset name or a similarity in (0, 1]."""
        SearchSettings.parse_fuzzy_threshold(value)  # validate
        Settings.set(storage, SearchSettings.FUZZY_THRESHOLD_KEY, value.strip().lower())

    @staticmethod
    def reset_fuzzy_threshold(storage: Storage) -> None:
        """Back to the default fuzzy threshold."""
        SearchSettings.set_fuzzy_threshold(storage, SearchSettings.DEFAULT_FUZZY_THRESHOLD)

    @staticmethod
    def parse_proximity_distance(value: str | int) -> int:
        """Resolve a proximity distance to a number of words.

        `value` is a preset name (`tight`, `medium`, `loose`) or a whole number of
        words from 1 to `PROXIMITY_MAX_DISTANCE`. Raises `InvalidSettingValueError`
        for anything else (0 words is a phrase - use the full-text engine with a
        "quoted phrase").
        """
        invalid = InvalidSettingValueError(
            f"distance must be one of {tuple(SearchSettings.PROXIMITY_PRESETS)} or a whole "
            f"number of words from 1 to {SearchSettings.PROXIMITY_MAX_DISTANCE}"
        )
        if isinstance(value, str):
            text = value.strip().lower()
            preset = SearchSettings.PROXIMITY_PRESETS.get(text)
            if preset is not None:
                return preset
            try:
                number = int(text)
            except ValueError:
                raise invalid from None
        elif isinstance(value, bool) or not isinstance(value, int):
            raise invalid
        else:
            number = value
        if not 1 <= number <= SearchSettings.PROXIMITY_MAX_DISTANCE:
            raise invalid
        return number

    @staticmethod
    def get_proximity_distance_setting(storage: Storage) -> str:
        """The stored proximity distance as set - a preset name or a number. 'medium' by default."""
        value = Settings.get(storage, SearchSettings.PROXIMITY_DISTANCE_KEY)
        if value is None:
            return SearchSettings.DEFAULT_PROXIMITY_DISTANCE
        try:
            SearchSettings.parse_proximity_distance(value)
        except InvalidSettingValueError:
            return SearchSettings.DEFAULT_PROXIMITY_DISTANCE
        return value

    @staticmethod
    def get_proximity_distance(storage: Storage) -> int:
        """Most words a `proximity` search allows between its first and last term. 10 by default."""
        return SearchSettings.parse_proximity_distance(
            SearchSettings.get_proximity_distance_setting(storage)
        )

    @staticmethod
    def set_proximity_distance(storage: Storage, value: str) -> None:
        """Store the default proximity distance: a preset name or a number of words."""
        SearchSettings.parse_proximity_distance(value)  # validate
        Settings.set(storage, SearchSettings.PROXIMITY_DISTANCE_KEY, value.strip().lower())

    @staticmethod
    def reset_proximity_distance(storage: Storage) -> None:
        """Back to the default proximity distance."""
        SearchSettings.set_proximity_distance(storage, SearchSettings.DEFAULT_PROXIMITY_DISTANCE)

    @staticmethod
    def parse_unicode(value: str, *, allow_auto: bool = False) -> str:
        """Resolve a Unicode setting: `off`, `basic` (NFC), `full` (NFKC, accents folded) or
        (when stored) `auto`. Raises `InvalidSettingValueError` for anything else."""
        text = value.strip().lower() if isinstance(value, str) else ""
        allowed = SearchSettings.UNICODE_VALUES if allow_auto else SearchSettings.UNICODE_LEVELS
        if text not in allowed:
            raise InvalidSettingValueError(f"unicode must be one of {', '.join(allowed)}")
        return text

    @staticmethod
    def get_unicode(storage: Storage) -> str:
        """The stored Unicode setting: a level, or `auto` (each engine's own default)."""
        value = Settings.get(storage, SearchSettings.NORMALIZE_UNICODE_KEY)
        if value is None:
            return SearchSettings.NORMALIZE_AUTO
        try:
            return SearchSettings.parse_unicode(value, allow_auto=True)
        except InvalidSettingValueError:
            return SearchSettings.NORMALIZE_AUTO

    @staticmethod
    def set_unicode(storage: Storage, value: str) -> None:
        """Store the Unicode setting: `auto`, `off`, `basic` or `full`."""
        Settings.set(
            storage,
            SearchSettings.NORMALIZE_UNICODE_KEY,
            SearchSettings.parse_unicode(value, allow_auto=True),
        )

    @staticmethod
    def reset_unicode(storage: Storage) -> None:
        """Back to `auto`: each engine's own Unicode handling."""
        SearchSettings.set_unicode(storage, SearchSettings.NORMALIZE_AUTO)

    @staticmethod
    def resolve_unicode(storage: Storage, default: str) -> str:
        """The Unicode level to use: the stored one, or `default` (an engine's own, see
        `UNICODE_DEFAULTS`) on `auto`."""
        stored = SearchSettings.get_unicode(storage)
        return default if stored == SearchSettings.NORMALIZE_AUTO else stored

    @staticmethod
    def parse_leetspeak(value: str, *, allow_auto: bool = False) -> str:
        """Resolve a leetspeak setting: `off`, `basic`, `standard`, `extended` or (when stored)
        `auto`. Raises `InvalidSettingValueError` for anything else."""
        text = value.strip().lower() if isinstance(value, str) else ""
        allowed = (
            SearchSettings.LEETSPEAK_VALUES if allow_auto else SearchSettings.LEETSPEAK_VALUES[1:]
        )
        if text not in allowed:
            raise InvalidSettingValueError(f"leetspeak must be one of {', '.join(allowed)}")
        return text

    @staticmethod
    def get_leetspeak(storage: Storage) -> str:
        """The stored leetspeak setting: a level, `off`, or `auto` (each engine's own default).

        A database that only has the older level setting reads it as that level.
        """
        for key in (SearchSettings.NORMALIZE_LEETSPEAK_KEY, SearchSettings.LEGACY_LEETSPEAK_KEY):
            value = Settings.get(storage, key)
            if value is not None:
                try:
                    return SearchSettings.parse_leetspeak(value, allow_auto=True)
                except InvalidSettingValueError:
                    break
        return SearchSettings.NORMALIZE_AUTO

    @staticmethod
    def set_leetspeak(storage: Storage, value: str) -> None:
        """Store the leetspeak setting: `auto`, `off`, `basic`, `standard` or `extended`."""
        Settings.set(
            storage,
            SearchSettings.NORMALIZE_LEETSPEAK_KEY,
            SearchSettings.parse_leetspeak(value, allow_auto=True),
        )

    @staticmethod
    def reset_leetspeak(storage: Storage) -> None:
        """Back to `auto`: each engine's own leetspeak handling."""
        SearchSettings.set_leetspeak(storage, SearchSettings.NORMALIZE_AUTO)

    @staticmethod
    def resolve_leetspeak(storage: Storage, default: str) -> str:
        """The leetspeak level to use: the stored one, or `default` (an engine's own) on `auto`."""
        stored = SearchSettings.get_leetspeak(storage)
        return default if stored == SearchSettings.NORMALIZE_AUTO else stored

    @staticmethod
    def parse_noise_level(value: str) -> str:
        """Resolve a noise level name (`low`, `medium` or `high`).

        Raises `InvalidSettingValueError` for anything else.
        """
        text = value.strip().lower() if isinstance(value, str) else ""
        if text not in SearchSettings.NOISE_LEVELS:
            raise InvalidSettingValueError(
                f"noise must be one of {', '.join(SearchSettings.NOISE_LEVELS)}"
            )
        return text

    @staticmethod
    def get_noise_level(storage: Storage) -> str:
        """How much noise the `noise-fuzzy` engine skips. 'low' by default."""
        value = Settings.get(storage, SearchSettings.NOISE_KEY)
        if value is None:
            return SearchSettings.DEFAULT_NOISE
        try:
            return SearchSettings.parse_noise_level(value)
        except InvalidSettingValueError:
            return SearchSettings.DEFAULT_NOISE

    @staticmethod
    def set_noise_level(storage: Storage, level: str) -> None:
        """Store the default noise level: `low`, `medium` or `high`."""
        Settings.set(storage, SearchSettings.NOISE_KEY, SearchSettings.parse_noise_level(level))

    @staticmethod
    def reset_noise_level(storage: Storage) -> None:
        """Back to the default noise level."""
        SearchSettings.set_noise_level(storage, SearchSettings.DEFAULT_NOISE)
