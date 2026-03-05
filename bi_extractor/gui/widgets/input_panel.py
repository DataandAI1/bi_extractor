"""Input panel with file/folder browse dialogs and drag-and-drop zone."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

from bi_extractor.core.registry import get_registry
from bi_extractor.gui.dnd import bind_drop, is_dnd_available


class InputPanel(ttk.LabelFrame):
    """Panel for selecting input files and folders."""

    def __init__(
        self,
        parent: tk.Widget,
        on_files_changed: Callable[[list[Path]], None],
    ) -> None:
        super().__init__(parent, text="Input", padding=10)
        self._on_files_changed = on_files_changed
        self._paths: list[Path] = []
        self._recursive_var = tk.BooleanVar(value=True)
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the input panel UI components."""
        # Drop zone
        self._drop_frame = tk.Frame(
            self,
            height=80,
            highlightbackground="#999999",
            highlightthickness=2,
            highlightcolor="#4a90d9",
            bg="#f5f5f5",
        )
        self._drop_frame.pack(fill=tk.X, pady=(0, 8))
        self._drop_frame.pack_propagate(False)

        if is_dnd_available():
            drop_text = "Drag files or folders here\n(or use Browse buttons below)"
        else:
            drop_text = (
                "Browse for files or folders below\n"
                "(install tkinterdnd2 for drag-and-drop)"
            )

        self._drop_label = tk.Label(
            self._drop_frame,
            text=drop_text,
            fg="#666666",
            bg="#f5f5f5",
            font=("TkDefaultFont", 10),
        )
        self._drop_label.pack(expand=True)

        # Register drag-and-drop on the drop zone
        dnd_bound = bind_drop(self._drop_frame, self._on_drop)
        if dnd_bound:
            bind_drop(self._drop_label, self._on_drop)

        # Button row
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Button(
            btn_frame, text="Browse Files...", command=self._browse_files
        ).pack(side=tk.LEFT, padx=(0, 6))

        ttk.Button(
            btn_frame, text="Browse Folder...", command=self._browse_folder
        ).pack(side=tk.LEFT, padx=(0, 12))

        ttk.Checkbutton(
            btn_frame,
            text="Recursive",
            variable=self._recursive_var,
        ).pack(side=tk.LEFT)

        # Summary label
        self._summary_label = ttk.Label(self, text="No files selected")
        self._summary_label.pack(fill=tk.X)

    def _browse_files(self) -> None:
        """Open a file dialog filtered to supported BI file extensions."""
        registry = get_registry()
        exts = sorted(registry.supported_extensions())
        ext_pattern = " ".join(f"*{e}" for e in exts)
        filetypes = [
            ("BI Report Files", ext_pattern),
            ("All Files", "*.*"),
        ]

        paths = filedialog.askopenfilenames(
            title="Select BI Report Files",
            filetypes=filetypes,
            initialdir=str(Path.cwd()),
        )

        if paths:
            new_paths = [Path(p) for p in paths]
            # Add to existing selection (avoid duplicates)
            existing = {p.resolve() for p in self._paths}
            for p in new_paths:
                if p.resolve() not in existing:
                    self._paths.append(p)
                    existing.add(p.resolve())
            self._update_summary()

    def _browse_folder(self) -> None:
        """Open a folder picker dialog."""
        folder = filedialog.askdirectory(
            title="Select Folder Containing BI Reports",
            initialdir=str(Path.cwd()),
        )

        if folder:
            folder_path = Path(folder)
            # Replace file selections with folder
            self._paths = [folder_path]
            self._update_summary()

    def _on_drop(self, paths: list[str]) -> None:
        """Handle files/folders dropped onto the drop zone."""
        new_paths = [Path(p) for p in paths if Path(p).exists()]
        if new_paths:
            existing = {p.resolve() for p in self._paths}
            for p in new_paths:
                if p.resolve() not in existing:
                    self._paths.append(p)
                    existing.add(p.resolve())
            self._update_summary()

    def _update_summary(self) -> None:
        """Update the summary label to reflect current selection."""
        if not self._paths:
            self._summary_label.config(text="No files selected")
        elif len(self._paths) == 1 and self._paths[0].is_dir():
            name = self._paths[0].name
            mode = "recursive" if self._recursive_var.get() else "non-recursive"
            self._summary_label.config(
                text=f"Selected: folder '{name}' ({mode})"
            )
        else:
            exts = sorted({p.suffix.lower() for p in self._paths if p.suffix})
            ext_str = ", ".join(exts) if exts else "unknown"
            self._summary_label.config(
                text=f"Selected: {len(self._paths)} file(s) ({ext_str})"
            )
        self._on_files_changed(self._paths)

    def get_paths(self) -> list[Path]:
        """Return the currently selected paths."""
        return list(self._paths)

    def get_recursive(self) -> bool:
        """Return the state of the recursive checkbox."""
        return self._recursive_var.get()

    def clear(self) -> None:
        """Reset all selection state."""
        self._paths.clear()
        self._summary_label.config(text="No files selected")
        self._on_files_changed(self._paths)

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the panel's interactive elements."""
        state = "normal" if enabled else "disabled"
        for child in self.winfo_children():
            if isinstance(child, ttk.Frame):
                for btn in child.winfo_children():
                    if isinstance(btn, (ttk.Button, ttk.Checkbutton)):
                        btn.config(state=state)
