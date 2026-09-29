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
    ENGINES = (ENGINE_ALL, "like", "exact", "full-text", "fuzzy", "proximity")
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
    def is_case_sensitive(storage: Storage) -> bool:
        """Whether `search` matches case-sensitively by default. Disabled by default.

        Only the `like` and `fuzzy` engines act on it: `exact` is always case-sensitive
        and `full-text` never is.
        """
        return Settings.get(storage, SearchSettings.CASE_SENSITIVE_KEY) == "true"

    @staticmethod
    def set_case_sensitive(storage: Storage, enabled: bool) -> None:
        Settings.set(storage, SearchSettings.CASE_SENSITIVE_KEY, "true" if enabled else "false")

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
