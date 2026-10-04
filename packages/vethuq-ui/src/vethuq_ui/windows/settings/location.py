"""Settings > Location: view and change where VethuQ keeps its data and its database backups,
the UI's equivalent of `vethuq settings location` and `vethuq settings location backups`."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, ttk

from vethuq_core.db.backup import Backup, BackupError
from vethuq_core.index.runner import IndexRunner
from vethuq_core.paths import Paths
from vethuq_core.storage import default_db_path

from vethuq_ui.dialogs import ask_yes_no, show_error, show_warning
from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.widgets import Widgets
from vethuq_ui.windows.placement import Placement


class LocationWindow:
    class Target:
        """One relocatable location. Subclasses say what it is and how to move it."""

        key = ""
        title = ""
        heading = ""
        can_reset = False
        restart_needed = False

        @staticmethod
        def current() -> Path:
            raise NotImplementedError

        @staticmethod
        def source_note() -> str:
            raise NotImplementedError

        @staticmethod
        def confirmation(target: Path) -> str:
            """What the change will do, shown before it is applied. Raises if it is not allowed."""
            raise NotImplementedError

        @staticmethod
        def apply(target: Path) -> None:
            raise NotImplementedError

        @staticmethod
        def is_default() -> bool:
            return True

        @staticmethod
        def reset() -> None:
            raise NotImplementedError

    class App(Target):
        key = "app"
        title = "App Location"
        heading = "Where VethuQ keeps its data (database, logs and run files)"
        restart_needed = True

        @staticmethod
        def current() -> Path:
            return Paths.default_data_root()

        @staticmethod
        def source_note() -> str:
            if Paths.env_location():
                return f"Set by the {Paths.ENV_VAR} environment variable"
            if Paths.configured_location():
                return "Set by you"
            return "The platform default"

        @staticmethod
        def _check_not_running() -> None:
            if IndexRunner.is_running()[0]:
                raise ValueError("Indexing is running. Stop it before changing the location.")

        @staticmethod
        def confirmation(target: Path) -> str:
            source = Paths.default_data_root()
            LocationWindow.App._check_not_running()
            folders = Paths.plan_move(source, target)  # raises ValueError if unsafe
            names = ", ".join(f.name + "/" for f in folders) or "nothing yet"
            return (
                f"This will move {names} from {source} to {target} "
                "and use the new location from now on."
            )

        @staticmethod
        def apply(target: Path) -> None:
            LocationWindow.App._check_not_running()
            Paths.move_data(Paths.default_data_root(), target)

    class Backups(Target):
        key = "backups"
        title = "Backups Location"
        heading = "Where database backups are kept"
        can_reset = True

        @staticmethod
        def current() -> Path:
            return Paths.backups_dir(default_db_path(), create=False)

        @staticmethod
        def source_note() -> str:
            if Paths.configured_backups_location():
                return "Set by you"
            return "The default, next to the database"

        @staticmethod
        def confirmation(target: Path) -> str:
            db_path = default_db_path()
            count = len(Backup.entries(db_path))
            return (
                f"This will move {count} backup(s) from {Paths.backups_dir(db_path)} to {target} "
                "and keep new backups there from now on."
            )

        @staticmethod
        def apply(target: Path) -> None:
            Backup.move_directory(default_db_path(), target)

        @staticmethod
        def is_default() -> bool:
            return Paths.configured_backups_location() is None

        @staticmethod
        def reset() -> None:
            Backup.reset_directory(default_db_path())

    _open: dict[str, tk.Toplevel] = {}

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        target: type[LocationWindow.Target],
        on_status: Callable[[str], None] = lambda _text: None,
    ) -> None:
        """Open the window for `target`, or bring the already-open one to the front."""
        existing = LocationWindow._open.get(target.key)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        window = tk.Toplevel(parent)
        LocationWindow._open[target.key] = window
        window.title(target.title)
        window.resizable(False, False)
        window.transient(parent)

        body = ttk.Frame(window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=target.heading, font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        path_var = tk.StringVar()
        note_var = tk.StringVar()
        ttk.Label(body, textvariable=path_var, wraplength=420, justify=tk.LEFT).pack(
            anchor=tk.W, pady=(10, 0)
        )
        ttk.Label(body, textvariable=note_var, foreground="grey").pack(anchor=tk.W, pady=(2, 0))

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(buttons, text="Close", width=9, command=window.destroy).pack(side=tk.RIGHT)
        change_button = PrimaryButton.build(buttons, "Browse...")
        change_button.pack(side=tk.RIGHT, padx=(0, 6))
        reset_button = Widgets.danger_button(buttons, "Reset")
        if target.can_reset:
            reset_button.pack(side=tk.RIGHT, padx=(0, 6))

        def refresh() -> None:
            path_var.set(str(target.current()))
            note_var.set(target.source_note())
            Widgets.set_danger_enabled(reset_button, not target.is_default())

        def finished(message: str) -> None:
            refresh()
            on_status(message)
            if target.restart_needed:
                show_warning(
                    window, target.title, "Restart VethuQ for the new location to take effect."
                )

        def change() -> None:
            chosen = filedialog.askdirectory(
                parent=window, initialdir=str(target.current()), mustexist=False
            )
            if not chosen:
                return
            new_path = Path(chosen).expanduser().absolute()
            try:
                message = target.confirmation(new_path)
            except (ValueError, OSError, BackupError) as exc:
                show_error(window, target.title, str(exc))
                return
            if not ask_yes_no(window, target.title, f"{message}\n\nContinue?"):
                return
            try:
                target.apply(new_path)
            except (ValueError, OSError, BackupError) as exc:
                show_error(window, target.title, f"Could not change the location: {exc}")
                return
            finished(f"{target.title} set to {new_path}")

        def reset() -> None:
            if not ask_yes_no(
                window,
                target.title,
                "Go back to keeping database backups next to the database, moving them back?",
            ):
                return
            try:
                target.reset()
            except (OSError, BackupError) as exc:
                show_error(window, target.title, f"Could not reset the location: {exc}")
                return
            finished(f"{target.title} reset to the default")

        change_button.configure(command=change)
        reset_button.configure(command=reset)
        refresh()
        Placement.center_on_main(window)
        window.bind("<Escape>", lambda _event: window.destroy())
        window.focus_set()
