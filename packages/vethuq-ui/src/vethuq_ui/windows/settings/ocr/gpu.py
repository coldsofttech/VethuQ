"""Settings > OCR > GPU: whether OCR uses the GPU, the UI's equivalent of
`vethuq settings gpu`."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from vethuq_core.settings import GpuSettings
from vethuq_core.storage import Storage

from vethuq_ui.buttons.primary import PrimaryButton
from vethuq_ui.windows.placement import Placement
from vethuq_ui.windows.settings.reset import ResetAction


class GpuWindow:
    _open: tk.Toplevel | None = None

    @staticmethod
    def show(
        parent: tk.Tk | tk.Toplevel,
        storage: Storage,
        on_status: Callable[[str], None] = lambda _text: None,
        on_applied: Callable[[], None] = lambda: None,
    ) -> None:
        """Open the window, or bring the already-open one to the front."""
        existing = GpuWindow._open
        if existing is not None and existing.winfo_exists():
            existing.lift()
            existing.focus_force()
            return

        window = tk.Toplevel(parent)
        GpuWindow._open = window
        window.title("OCR GPU")
        window.resizable(False, False)
        window.transient(parent)

        body = ttk.Frame(window, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Use the GPU for OCR", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        ttk.Label(
            body,
            text=(
                "It only takes effect if a CUDA-capable PaddleOCR build with a visible GPU "
                "is installed. Otherwise OCR falls back to the CPU automatically."
            ),
            foreground="grey",
            wraplength=380,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 8))

        enabled_var = tk.BooleanVar(value=GpuSettings.is_enabled(storage))
        ttk.Radiobutton(body, text="Enabled", value=True, variable=enabled_var).pack(
            anchor=tk.W, pady=(6, 0)
        )
        ttk.Radiobutton(body, text="Disabled (default)", value=False, variable=enabled_var).pack(
            anchor=tk.W, pady=(6, 0)
        )

        def apply() -> None:
            enabled = enabled_var.get()
            GpuSettings.set_enabled(storage, enabled)
            on_status(
                "GPU enabled for OCR (falls back to the CPU if none is available)"
                if enabled
                else "GPU disabled: OCR will run on the CPU"
            )
            on_applied()
            window.destroy()

        buttons = ttk.Frame(body)
        buttons.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(buttons, text="Cancel", width=9, command=window.destroy).pack(side=tk.RIGHT)
        PrimaryButton.build(buttons, "Apply", apply).pack(side=tk.RIGHT, padx=(0, 6))
        ResetAction.add(
            window,
            buttons,
            title="OCR GPU",
            default_label="disabled",
            is_default=lambda: GpuSettings.is_enabled(storage) == GpuSettings.DEFAULT_ENABLED,
            reset=lambda: GpuSettings.reset(storage),
            status="GPU reset to the default (disabled)",
            on_status=on_status,
            on_applied=on_applied,
        )
        window.bind("<Return>", lambda _event: apply())
        window.bind("<Escape>", lambda _event: window.destroy())
        Placement.center_on_main(window)
        window.focus_set()
