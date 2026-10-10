"""What to tell the user about an update, and what their answer does. No Tk, so it is testable
anywhere; `update_prompt` draws it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from vethuq_core.settings import UpdateSettings
from vethuq_core.storage import Storage
from vethuq_core.updates import UpdateResult, UpdateStatus


@dataclass(frozen=True)
class UpdatePlan:
    """How to tell the user: a `dialog` or a status-bar `message`, and which choices it offers."""

    kind: str  # 'dialog' or 'message'
    title: str
    message: str
    choices: tuple[tuple[str, str], ...] = ()  # (action, label) for a dialog
    release_notes_url: str | None = None

    LATER = "later"
    SKIP = "skip"
    OK = "ok"

    @staticmethod
    def for_result(result: UpdateResult) -> UpdatePlan | None:
        """What to show for `result`, or None when there is nothing to say."""
        if not result.notify or not result.message:
            return None
        choices: tuple[tuple[str, str], ...]
        if result.status is UpdateStatus.BELOW_MINIMUM:
            # Only explains why some features are held back, so it can't be snoozed or skipped.
            title = "VethuQ update recommended"
            choices = ((UpdatePlan.OK, "OK"),)
        elif result.status is UpdateStatus.AVAILABLE:
            title = "VethuQ update available"
            choices = ((UpdatePlan.LATER, "Later"), (UpdatePlan.SKIP, "Skip this version"))
        else:
            title = "VethuQ update"
            choices = ((UpdatePlan.LATER, "Later"),)
        # 'notify-only' never opens a dialog: the status bar says it and that is all.
        kind = "dialog" if result.mode == "on" else "message"
        return UpdatePlan(kind, title, result.message, choices, result.release_notes_url)

    @staticmethod
    def apply(
        storage: Storage, result: UpdateResult, action: str, on_status: Callable[[str], None]
    ) -> None:
        """Remember the user's answer."""
        if action == UpdatePlan.LATER:
            UpdateSettings.snooze(storage)
            on_status("Update reminder snoozed for a day")
        elif action == UpdatePlan.SKIP and result.latest:
            UpdateSettings.skip_version(storage, result.latest)
            on_status(f"VethuQ {result.latest} will not be announced again")
