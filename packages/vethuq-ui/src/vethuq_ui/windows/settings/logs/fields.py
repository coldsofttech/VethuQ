"""The logging settings as editable fields: level and retention."""

from __future__ import annotations

from vethuq_core.settings import LogSettings
from vethuq_core.storage import Storage

from vethuq_ui.windows.settings.fields import ChoiceField, NumberField


class LogFields:
    RETENTION_MAX_DAYS = 365

    @staticmethod
    def level(storage: Storage) -> ChoiceField:
        return ChoiceField(
            storage,
            "Log level",
            "How much detail VethuQ writes to its log files. Debug is the most, error the least.",
            "Log level",
            LogSettings.DEFAULT_LEVEL,
            LogSettings.get_level,
            LogSettings.set_level,
            LogSettings.reset_level,
            choices=[(value, value.capitalize()) for value in LogSettings.LEVEL_VALUES],
        )

    @staticmethod
    def retention(storage: Storage) -> NumberField:
        return NumberField(
            storage,
            "Log retention",
            "How many days of daily log files are kept before they are deleted.",
            "Log retention",
            str(LogSettings.DEFAULT_RETENTION_DAYS),
            LogSettings.get_retention_days,
            lambda s, v: LogSettings.set_retention_days(s, int(v)),
            LogSettings.reset_retention_days,
            minimum=1,
            maximum=LogFields.RETENTION_MAX_DAYS,
            step=1,
            unit="days",
        )
