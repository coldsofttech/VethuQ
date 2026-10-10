"""VethuQ desktop UI: Settings > Sources to add folders/files and manage registered sources."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

import sv_ttk
from vethuq_core.errors import StartupError
from vethuq_core.policy import PolicyService
from vethuq_core.storage import Storage, open_storage

from vethuq_ui.dialogs import show_error
from vethuq_ui.icons import Brand
from vethuq_ui.index_controls import IndexControls
from vethuq_ui.logging import UiLogging
from vethuq_ui.ribbon import Ribbon, RibbonActions
from vethuq_ui.search_view import SearchView
from vethuq_ui.source_list import SourceListView
from vethuq_ui.status_bar import StatusBar
from vethuq_ui.update_prompt import UpdatePrompt
from vethuq_ui.windows.settings.about import AboutWindow
from vethuq_ui.windows.settings.database.field_window import DatabaseFieldWindow
from vethuq_ui.windows.settings.index.background_service import BackgroundServiceWindow
from vethuq_ui.windows.settings.index.retention import RemovedRetentionWindow
from vethuq_ui.windows.settings.index.stability import StabilityCheckWindow
from vethuq_ui.windows.settings.index.stale_lock import StaleLockWindow
from vethuq_ui.windows.settings.index.workers import ThreadWorkersWindow
from vethuq_ui.windows.settings.location import LocationWindow
from vethuq_ui.windows.settings.logs.field_window import LogFieldWindow
from vethuq_ui.windows.settings.ocr.engine import OcrEngineWindow
from vethuq_ui.windows.settings.ocr.gpu import GpuWindow
from vethuq_ui.windows.settings.ocr.languages import OcrLanguagesWindow
from vethuq_ui.windows.settings.ocr.retry import OcrRetryWindow
from vethuq_ui.windows.settings.search.field_window import SearchFieldWindow
from vethuq_ui.windows.settings.updates import UpdatesWindow

_logger = UiLogging.logger


class MainWindow(tk.Tk):
    def __init__(self, storage: Storage | None = None, db_path: Path | None = None) -> None:
        UiLogging.configure(db_path)
        super().__init__()
        try:
            self.storage = storage or open_storage(db_path)
        except StartupError:
            super().destroy()  # don't leave an empty window behind the error dialog
            raise
        self._db_path = db_path
        _logger.info("VethuQ UI started")
        policy_refresh = PolicyService.start(_logger)  # in the background: never delays startup

        self.title("VethuQ")
        Brand.apply_window_icon(self)
        self.geometry("720x480")
        try:
            self.state("zoomed")
        except tk.TclError:
            self.attributes("-zoomed", True)
        sv_ttk.set_theme("light")

        # The views are built and packed in this order (ribbon on top, status bar
        # at the bottom, then the two switchable views fill the rest). The actions
        # below look the views up lazily, so they can be defined before the views exist.
        self.ribbon = Ribbon(
            self,
            self.storage,
            RibbonActions(
                show_search=self.on_show_search,
                add_folder=lambda: self.sources.on_add_folder(),
                add_file=lambda: self.sources.on_add_file(),
                show_source_list=self.on_show_source_list,
                toggle_pause_resume=lambda: self.index_controls.toggle_pause_resume(),
                stop=lambda: self.index_controls.stop(),
                delete_source=lambda: self.sources.delete_selected(),
                show_about=lambda: AboutWindow.show(self),
                show_updates=lambda: UpdatesWindow.show(
                    self, self.storage, self.status_bar.show_message
                ),
                show_gpu=lambda: GpuWindow.show(
                    self,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_ocr_retry=lambda: OcrRetryWindow.show(
                    self,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_ocr_engine=lambda: OcrEngineWindow.show(
                    self,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_ocr_languages=lambda: OcrLanguagesWindow.show(
                    self,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_search_field=lambda name: SearchFieldWindow.show(
                    self,
                    name,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_removed_retention=lambda: RemovedRetentionWindow.show(
                    self, self.storage, self.status_bar.show_message
                ),
                show_stability_check=lambda: StabilityCheckWindow.show(
                    self,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_thread_workers=lambda: ThreadWorkersWindow.show(
                    self,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_stale_lock=lambda: StaleLockWindow.show(
                    self,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_background_service=lambda: BackgroundServiceWindow.show(
                    self, self.status_bar.show_message, self.ribbon.refresh_setting_icons
                ),
                show_db_field=lambda name: DatabaseFieldWindow.show(
                    self,
                    name,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_log_field=lambda name: LogFieldWindow.show(
                    self,
                    name,
                    self.storage,
                    self.status_bar.show_message,
                    self.ribbon.refresh_setting_icons,
                ),
                show_app_location=lambda: LocationWindow.show(
                    self, LocationWindow.App, self.status_bar.show_message
                ),
                show_backups_location=lambda: LocationWindow.show(
                    self, LocationWindow.Backups, self.status_bar.show_message
                ),
            ),
        )
        self.ribbon.pack(side=tk.TOP, fill=tk.X)
        self.status_bar = StatusBar(self)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.search = SearchView(self, self.storage)
        self.sources = SourceListView(
            self,
            self.storage,
            db_path,
            on_index=lambda source_id, restart: self.index_controls.start_targeted_run(
                source_id, restart=restart
            ),
            on_source_added=lambda: self.index_controls.launch_or_attach(),
            on_selection_changed=self.ribbon.set_delete_visible,
        )
        self.index_controls = IndexControls(
            self, db_path, self.ribbon, self.status_bar, self.sources.refresh
        )

        self.on_show_search()
        self.index_controls.launch_or_attach()
        self.index_controls.start_polling()
        UpdatePrompt.start(self, self.storage, self.status_bar.show_message, policy_refresh)

    def report_callback_exception(self, exc: type, val: BaseException, tb: Any) -> None:
        # Tk's default just prints to stderr, invisible once the app is
        # launched as a GUI (no attached console) - log it instead, e.g. an
        # exception raised inside a button's command silently doing nothing.
        _logger.error("Unhandled error in a UI callback", exc_info=(exc, val, tb))

    def destroy(self) -> None:
        self.index_controls.shutdown()
        _logger.info("VethuQ UI stopped")
        super().destroy()

    def on_show_source_list(self) -> None:
        self.search.pack_forget()
        if not self.sources.winfo_ismapped():
            self.sources.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        self.sources.refresh()

    def on_show_search(self) -> None:
        self.sources.pack_forget()
        if not self.search.winfo_ismapped():
            self.search.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)


def main() -> None:
    try:
        window = MainWindow()
    except StartupError as exc:
        _logger.error("%s", exc)
        root = tk.Tk()
        root.withdraw()
        show_error(root, "VethuQ can't start", str(exc))
        root.destroy()
        raise SystemExit(exc.exit_code) from None
    window.mainloop()


if __name__ == "__main__":
    main()
