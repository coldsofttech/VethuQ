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
    DEFAULT_ENGINE = "like"
    ENGINES = ("like", "exact", "full-text", "fuzzy")
    CASE_SENSITIVE_KEY = "search_case_sensitive"
    FUZZY_THRESHOLD_KEY = "search_fuzzy_threshold"
    DEFAULT_FUZZY_THRESHOLD = "balanced"
    # Minimum similarity (0-1] between a query word and a page word for the `fuzzy`
    # engine to count it as a match, by name.
    FUZZY_PRESETS = {"strict": 0.90, "balanced": 0.80, "loose": 0.65}

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
        """Default engine `search` uses when none is given. 'like' by default."""
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
        """Resolve a fuzzy threshold - a preset name or a similarity in (0, 1] - to that similarity.

        Raises `InvalidSettingValueError` for anything else.
        """
        if isinstance(value, str):
            preset = SearchSettings.FUZZY_PRESETS.get(value.strip().lower())
            if preset is not None:
                return preset
            try:
                number = float(value)
            except ValueError:
                raise InvalidSettingValueError(
                    f"threshold must be a number above 0 and up to 1, or one of "
                    f"{tuple(SearchSettings.FUZZY_PRESETS)}"
                ) from None
        else:
            number = float(value)
        if not 0 < number <= 1:
            raise InvalidSettingValueError("threshold must be above 0 and at most 1")
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
