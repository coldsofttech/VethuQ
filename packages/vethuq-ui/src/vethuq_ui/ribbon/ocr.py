"""The ribbon's OCR tab: GPU, retry and engine."""

from __future__ import annotations

import tkinter as tk

from vethuq_core.settings import GpuSettings, OcrSettings
from vethuq_core.storage import Storage

from vethuq_ui.ribbon.actions import RibbonActions
from vethuq_ui.ribbon.group import RibbonGroup
from vethuq_ui.ribbon.tab import IconTab


class OcrTab(IconTab):
    def __init__(self, parent: tk.Misc, storage: Storage, actions: RibbonActions) -> None:
        super().__init__(parent, storage)
        group = RibbonGroup.build(self, "OCR")
        self._add_button(
            group, actions.show_gpu, self.gpu_icon_name, "\N{HIGH VOLTAGE SIGN}", "GPU"
        )
        self._add_button(
            group,
            actions.show_ocr_retry,
            self.retry_icon_name,
            "\N{ANTICLOCKWISE OPEN CIRCLE ARROW}",
            "Retry",
        )
        self._add_button(
            group, actions.show_ocr_engine, self.engine_icon_name, "\N{GEAR}", "Engine"
        )

    def gpu_icon_name(self) -> str:
        return "gpu" if GpuSettings.is_enabled(self._storage) else "gpu-disable"

    def retry_icon_name(self) -> str:
        off = OcrSettings.get_retry_attempts(self._storage) == 0
        return self._variant("ocr-retry", "ocr-retry-disable", off)

    def engine_icon_name(self) -> str:
        return f"ocr-engine-{OcrSettings.get_engine(self._storage)}"
