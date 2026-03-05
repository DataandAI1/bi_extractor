"""Progress panel with progress bar and status label."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class ProgressPanel(ttk.LabelFrame):
    """Panel displaying extraction progress with bar and status text."""

    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(parent, text="Progress", padding=10)
        self._total = 0
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the progress panel UI components."""
        # Progress bar row
        bar_frame = ttk.Frame(self)
        bar_frame.pack(fill=tk.X, pady=(0, 4))

        self._progress_var = tk.DoubleVar(value=0)
        self._bar = ttk.Progressbar(
            bar_frame,
            orient=tk.HORIZONTAL,
            mode="determinate",
            variable=self._progress_var,
        )
        self._bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        self._counter_label = ttk.Label(bar_frame, text="", width=12, anchor=tk.E)
        self._counter_label.pack(side=tk.RIGHT)

        # Status label
        self._status_label = ttk.Label(self, text="", anchor=tk.W)
        self._status_label.pack(fill=tk.X)

    def set_total(self, total: int) -> None:
        """Set total file count and switch to determinate mode."""
        self._total = total
        self._bar.stop()
        self._bar.config(mode="determinate", maximum=total)
        self._progress_var.set(0)
        self._counter_label.config(text=f"0 / {total}")
        self._status_label.config(text="Starting extraction...")

    def set_current(self, current: int, file_name: str) -> None:
        """Update progress bar position and status label."""
        self._progress_var.set(current - 1)  # Fill as we start processing
        self._counter_label.config(text=f"{current} / {self._total}")
        self._status_label.config(
            text=f"Processing file {current} of {self._total}: {file_name}"
        )

    def set_complete(self, success_count: int, error_count: int) -> None:
        """Show completion message and fill the progress bar."""
        self._bar.stop()
        self._progress_var.set(self._total)
        self._counter_label.config(text=f"{self._total} / {self._total}")

        if error_count > 0:
            self._status_label.config(
                text=f"Complete: {success_count} extracted, {error_count} with errors"
            )
        else:
            self._status_label.config(
                text=f"Complete: {success_count} file(s) extracted successfully"
            )

    def set_indeterminate(self, message: str) -> None:
        """Switch to indeterminate mode for discovery phase."""
        self._bar.config(mode="indeterminate")
        self._bar.start(10)
        self._counter_label.config(text="")
        self._status_label.config(text=message)

    def reset(self) -> None:
        """Reset to initial empty state."""
        self._bar.stop()
        self._bar.config(mode="determinate", maximum=100)
        self._progress_var.set(0)
        self._total = 0
        self._counter_label.config(text="")
        self._status_label.config(text="")
