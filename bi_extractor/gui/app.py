"""Main GUI application window for bi-extractor."""

from __future__ import annotations

import platform
import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from bi_extractor.core.models import ExtractionResult
from bi_extractor.core.registry import get_registry
from bi_extractor.gui.dnd import get_dnd_base_class
from bi_extractor.gui.widgets.input_panel import InputPanel
from bi_extractor.gui.widgets.progress_panel import ProgressPanel
from bi_extractor.gui.widgets.results_panel import ResultsPanel
from bi_extractor.gui.worker import ExtractionWorker, MessageType, WorkerMessage

_Base = get_dnd_base_class()


class BiExtractorApp(_Base):  # type: ignore[misc]
    """Main application window for BI Metadata Extractor."""

    def __init__(self) -> None:
        super().__init__()

        # DPI awareness for Windows
        self._set_dpi_awareness()

        self.title("BI Metadata Extractor")
        self.minsize(900, 700)
        self.geometry("1050x750")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._worker: ExtractionWorker | None = None
        self._worker_queue: queue.Queue[WorkerMessage] = queue.Queue()
        self._results: list[ExtractionResult] = []

        self._build_menu()
        self._build_layout()
        self._set_status("Ready.")

    @staticmethod
    def _set_dpi_awareness() -> None:
        """Enable DPI awareness on Windows for crisp rendering."""
        if platform.system() == "Windows":
            try:
                import ctypes

                ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
            except (AttributeError, OSError):
                pass

    def _build_menu(self) -> None:
        """Build the application menu bar."""
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(
            label="Open Files...", command=self._menu_open_files
        )
        file_menu.add_command(
            label="Open Folder...", command=self._menu_open_folder
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Export to CSV...", command=self._export_csv
        )
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        # View menu
        view_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="View", menu=view_menu)
        view_menu.add_command(
            label="Clear Results", command=self._clear_results
        )

        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(
            label="Supported Formats", command=self._show_formats
        )
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self._show_about)

    def _build_layout(self) -> None:
        """Build the main application layout."""
        # Main container
        main_frame = ttk.Frame(self, padding=8)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Top section: Input + Progress + Buttons
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 4))

        # Input panel
        self._input_panel = InputPanel(top_frame, self._on_files_selected)
        self._input_panel.pack(fill=tk.X, pady=(0, 6))

        # Progress panel
        self._progress_panel = ProgressPanel(top_frame)
        self._progress_panel.pack(fill=tk.X, pady=(0, 6))

        # Action buttons
        btn_frame = ttk.Frame(top_frame)
        btn_frame.pack(fill=tk.X, pady=(0, 4))

        self._extract_btn = ttk.Button(
            btn_frame,
            text="Extract Metadata",
            command=self._start_extraction,
            state=tk.DISABLED,
        )
        self._extract_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._cancel_btn = ttk.Button(
            btn_frame,
            text="Cancel",
            command=self._cancel_extraction,
            state=tk.DISABLED,
        )
        self._cancel_btn.pack(side=tk.LEFT, padx=(0, 6))

        self._clear_btn = ttk.Button(
            btn_frame, text="Clear Results", command=self._clear_results
        )
        self._clear_btn.pack(side=tk.RIGHT)

        self._export_btn = ttk.Button(
            btn_frame,
            text="Export to CSV...",
            command=self._export_csv,
            state=tk.DISABLED,
        )
        self._export_btn.pack(side=tk.RIGHT, padx=(0, 6))

        self._row_count_label = ttk.Label(btn_frame, text="")
        self._row_count_label.pack(side=tk.RIGHT, padx=(0, 12))

        # Results panel (takes remaining space)
        self._results_panel = ResultsPanel(
            main_frame, on_row_count_changed=self._on_row_count_changed
        )
        self._results_panel.pack(fill=tk.BOTH, expand=True)

        # Status bar
        self._status_bar = ttk.Label(
            self, text="Ready.", relief=tk.SUNKEN, anchor=tk.W, padding=(6, 2)
        )
        self._status_bar.pack(side=tk.BOTTOM, fill=tk.X)

    # -- Callbacks -----------------------------------------------------------

    def _on_files_selected(self, paths: list[Path]) -> None:
        """Handle file selection changes from the input panel."""
        if paths:
            self._extract_btn.config(state=tk.NORMAL)
        else:
            self._extract_btn.config(state=tk.DISABLED)

    def _on_row_count_changed(self, count: int) -> None:
        """Update the row count label."""
        if count > 0:
            self._row_count_label.config(text=f"{count} fields total")
        else:
            self._row_count_label.config(text="")

    # -- Extraction ----------------------------------------------------------

    def _start_extraction(self) -> None:
        """Begin extraction in a background thread."""
        # Double-start protection
        if self._worker and self._worker.is_alive():
            return

        paths = self._input_panel.get_paths()
        if not paths:
            return

        # Reset state
        self._results.clear()
        self._results_panel.clear()
        self._worker_queue = queue.Queue()

        # Update UI state
        self._extract_btn.config(state=tk.DISABLED)
        self._cancel_btn.config(state=tk.NORMAL)
        self._export_btn.config(state=tk.DISABLED)
        self._input_panel.set_enabled(False)

        # Show discovery phase
        self._progress_panel.set_indeterminate("Discovering files...")
        self._set_status("Discovering files...")

        # Start worker
        self._worker = ExtractionWorker(
            paths=paths,
            recursive=self._input_panel.get_recursive(),
            message_queue=self._worker_queue,
        )
        self._worker.start()

        # Begin polling
        self.after(100, self._poll_worker)

    def _poll_worker(self) -> None:
        """Poll the worker queue for progress messages."""
        try:
            while True:
                msg = self._worker_queue.get_nowait()
                if msg.msg_type == MessageType.DISCOVERY_COMPLETE:
                    if msg.total == 0:
                        self._set_status(
                            "No supported BI files found in selected path(s)."
                        )
                        self._on_extraction_finished()
                        return
                    self._progress_panel.set_total(msg.total)
                    self._set_status(f"Extracting metadata from {msg.total} file(s)...")
                elif msg.msg_type == MessageType.FILE_START:
                    self._progress_panel.set_current(msg.current, msg.file_name)
                elif msg.msg_type == MessageType.FILE_COMPLETE:
                    if msg.result is not None:
                        self._results.append(msg.result)
                        self._results_panel.add_result(msg.result)
                elif msg.msg_type == MessageType.ALL_COMPLETE:
                    self._on_extraction_complete()
                    return
                elif msg.msg_type == MessageType.ERROR:
                    self._on_extraction_error(msg.error)
                    return
        except queue.Empty:
            pass

        if self._worker and self._worker.is_alive():
            self.after(100, self._poll_worker)
        else:
            # Fix: drain remaining messages after thread exit to avoid race
            self._drain_remaining_messages()

    def _drain_remaining_messages(self) -> None:
        """Process any messages left in the queue after the worker thread exits."""
        try:
            while True:
                msg = self._worker_queue.get_nowait()
                if msg.msg_type == MessageType.ALL_COMPLETE:
                    self._on_extraction_complete()
                    return
                elif msg.msg_type == MessageType.FILE_COMPLETE:
                    if msg.result is not None:
                        self._results.append(msg.result)
                        self._results_panel.add_result(msg.result)
                elif msg.msg_type == MessageType.ERROR:
                    self._on_extraction_error(msg.error)
                    return
        except queue.Empty:
            # Worker finished without ALL_COMPLETE — show partial results
            if self._results:
                self._on_extraction_complete()
            else:
                self._on_extraction_finished()

    def _on_extraction_complete(self) -> None:
        """Handle successful extraction completion."""
        success = sum(1 for r in self._results if not r.errors)
        errors = sum(1 for r in self._results if r.errors)
        self._progress_panel.set_complete(success, errors)

        total_fields = sum(len(r.fields) for r in self._results)
        self._set_status(
            f"Extraction complete: {len(self._results)} file(s), "
            f"{total_fields} fields extracted."
        )

        self._on_extraction_finished()
        if self._results:
            self._export_btn.config(state=tk.NORMAL)

    def _on_extraction_error(self, error: str) -> None:
        """Re-enable UI and show error — symmetric with _on_extraction_complete."""
        self._on_extraction_finished()
        self._progress_panel.reset()
        if error:
            messagebox.showerror("Extraction Error", error)
        self._set_status("Extraction failed.")

    def _on_extraction_finished(self) -> None:
        """Re-enable UI controls after extraction ends (success or error)."""
        self._extract_btn.config(state=tk.NORMAL)
        self._cancel_btn.config(state=tk.DISABLED)
        self._input_panel.set_enabled(True)

    def _cancel_extraction(self) -> None:
        """Cancel the current extraction."""
        if self._worker and self._worker.is_alive():
            self._worker.request_cancel()
            self._set_status("Cancelling...")
            self._cancel_btn.config(state=tk.DISABLED)

    # -- Export --------------------------------------------------------------

    def _export_csv(self) -> None:
        """Export results to CSV using the existing CsvFormatter."""
        results = self._results_panel.get_results()
        if not results:
            messagebox.showinfo("Export", "No results to export.")
            return

        chosen = filedialog.asksaveasfilename(
            title="Export Results to CSV",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile="BI_Metadata.csv",
            initialdir=str(Path.cwd()),
        )

        if not chosen:
            return

        try:
            from bi_extractor.output.csv_formatter import CsvFormatter

            chosen_path = Path(chosen)
            formatter = CsvFormatter()
            output = formatter.write(
                results, chosen_path.parent, filename=chosen_path.name
            )
            self._set_status(f"Exported to: {output}")
            messagebox.showinfo("Export", f"Results exported to:\n{output}")
        except OSError as e:
            messagebox.showerror("Export Error", f"Failed to write CSV:\n{e}")

    # -- UI Actions ----------------------------------------------------------

    def _clear_results(self) -> None:
        """Clear all results and reset progress."""
        self._results.clear()
        self._results_panel.clear()
        self._progress_panel.reset()
        self._export_btn.config(state=tk.DISABLED)
        self._set_status("Results cleared.")

    def _set_status(self, message: str) -> None:
        """Update the status bar text."""
        self._status_bar.config(text=message)

    def _on_close(self) -> None:
        """Handle window close."""
        if self._worker and self._worker.is_alive():
            self._worker.request_cancel()
        self.destroy()

    # -- Menu actions --------------------------------------------------------

    def _menu_open_files(self) -> None:
        """Trigger file browse from the menu."""
        self._input_panel._browse_files()

    def _menu_open_folder(self) -> None:
        """Trigger folder browse from the menu."""
        self._input_panel._browse_folder()

    def _show_formats(self) -> None:
        """Show supported file formats in a dialog."""
        registry = get_registry()
        parsers = registry.list_parsers()

        lines: list[str] = ["Supported BI Report Formats:\n"]
        for p in parsers:
            exts = ", ".join(str(e) for e in p["extensions"])  # type: ignore[union-attr]
            available = "Ready" if p["available"] else "Missing dependency"
            tool = str(p["tool"])
            lines.append(f"  {tool}: {exts} [{available}]")

        messagebox.showinfo("Supported Formats", "\n".join(lines))

    def _show_about(self) -> None:
        """Show the About dialog."""
        messagebox.showinfo(
            "About BI Metadata Extractor",
            "BI Metadata Extractor v0.1.0\n\n"
            "Universal BI Report Metadata Extractor\n\n"
            f"Python {sys.version.split()[0]}\n"
            f"Platform: {platform.platform()}",
        )
