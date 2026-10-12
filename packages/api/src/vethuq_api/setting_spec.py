"""What a setting is: its kind, its description, and the errors the settings screen can get."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

BOOLEAN, INTEGER, NUMBER, CHOICE = "boolean", "integer", "number", "choice"
MULTI, BANDS, TEXT, PATH = "multichoice", "bands", "text", "path"


class SettingNotFoundError(LookupError):
    """No such section or setting."""


class InvalidSettingError(ValueError):
    """The value is not allowed for the setting (the message says why)."""


@dataclass(frozen=True)
class Spec:
    """One setting. `read`, `write` and `reset` talk to the core client."""

    id: str
    section: str
    label: str
    description: str
    kind: str
    default: Any  # the value, or a function of the client when it depends on the installation
    read: Callable[[Any], Any]
    write: Callable[[Any, Any], None] | None  # None: shown, but not changed here
    reset: Callable[[Any], None] | None  # for a read-only setting, clears it; None: no reset
    options: Callable[[Any], list[dict[str, object]]] | None = None
    labels: tuple[str, ...] = ()
    group: str = ""  # a heading the screen puts above a run of related settings
    group_note: str = ""  # a line under that heading
    resettable: bool = True  # False when there is nothing to reset to
    # Returns why the setting cannot be changed now (for example an environment variable overrides
    # it), or "" when it can.
    locked: Callable[[Any], str] | None = None
    # A write that also takes the options sent with the value (`{"move": True}`); it replaces
    # `write`. `moves` means the setting relocates data, which needs the core client released.
    write_with: Callable[[Any, Any, dict[str, Any]], None] | None = None
    reset_with: Callable[[Any, dict[str, Any]], None] | None = None
    moves: bool = False
    # Exceptions a write or reset may raise for a value that is not usable, shown as the reason.
    catches: tuple[type[BaseException], ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    advanced: bool = False
    note: str | Callable[[Any], str] = ""
