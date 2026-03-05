# GUI Implementation Plan for bi_extractor

**Date:** 2026-03-04
**Status:** Reviewed (Architect + Critic consensus)
**Complexity:** MEDIUM-HIGH

---

## Context

The bi_extractor project is a CLI-only tool that extracts metadata from BI report files across 8 BI platforms (Tableau, SSRS, Cognos, BIRT, Jasper, Oracle BI Publisher, and more). The core engine in `bi_extractor/core/engine.py` exposes three functions: `discover_files()`, `extract_file()`, and `extract_all()`. An empty GUI placeholder exists at `bi_extractor/gui/__init__.py`.

The project currently has zero third-party runtime dependencies for core functionality (stdlib only: xml, zipfile, pathlib, csv, logging, argparse, dataclasses). It has 351 passing tests and enforces mypy strict mode.

This plan adds a graphical interface that wraps the existing engine without modifying any core logic, CLI code, or existing tests.

---

## Work Objectives

1. Build a tkinter/ttk-based GUI application that provides drag-and-drop file/folder input, a file browser dialog, real-time progress tracking, and a metadata results viewer.
2. Integrate the GUI as a thin presentation layer over the existing `bi_extractor.core.engine` module.
3. Use threading to keep the UI responsive during extraction operations.
4. Add a `gui` entry point so users can launch via `bi-extractor-gui` or `python -m bi_extractor.gui`.

---

## Guardrails

### Must Have
- Drag-and-drop file and folder input (Windows primary, cross-platform where possible)
- Traditional file/folder browse dialogs as alternative input method
- Real progress bar with per-file status messages during extraction
- Sortable, scrollable metadata table viewer for extraction results
- Export button to save results to CSV (reusing existing `CsvFormatter`)
- Threading: extraction runs in a background thread, UI remains responsive
- Works on Windows with Python 3.10+ and tkinter (ships with standard Python)
- No changes to any file under `bi_extractor/core/`, `bi_extractor/parsers/`, `bi_extractor/cli/`, or `bi_extractor/output/`
- All 351 existing tests continue to pass
- mypy strict compatibility for all new GUI code

### Must NOT Have
- No heavy third-party GUI frameworks (no PyQt, no Electron, no web frameworks)
- No modifications to the core engine, parsers, CLI, or output modules
- No new required runtime dependencies (tkinter is stdlib; tkinterdnd2 is optional for native drag-drop)
- No database or persistent state -- GUI is stateless between sessions
- No async/await patterns -- use `threading.Thread` for background work

---

## Technology Choice: tkinter/ttk

**Rationale:**
- **Zero dependencies**: tkinter ships with Python on Windows (and most Linux/macOS distributions). This preserves the project's stdlib-only philosophy.
- **ttk.Treeview**: Provides a native-looking sortable table widget, ideal for the metadata viewer.
- **Proven pattern**: `threading.Thread` + `root.after()` polling is the standard tkinter approach for non-blocking background operations.
- **Drag-and-drop**: Windows native drag-drop is supported via `tkinterdnd2` (optional pip install). The GUI will gracefully degrade to browse-only if `tkinterdnd2` is unavailable.
- **Cross-platform**: Works on Windows, macOS, and Linux without platform-specific code.

**Alternatives considered and rejected:**
- *customtkinter*: Adds a third-party dependency for cosmetic improvements; not worth the dependency.
- *PyQt/PySide*: Heavy dependency (~50MB+), GPL licensing concerns, overkill for this use case.
- *DearPyGui*: Not well-suited for table-heavy data display.

---

## Architecture

```
bi_extractor/
  gui/
    __init__.py          # Package docstring + launch_gui() entry point
    app.py               # BiExtractorApp(tk.Tk) -- main window, layout, lifecycle
    widgets/
      __init__.py        # Package init
      input_panel.py     # InputPanel(ttk.LabelFrame) -- drop zone + browse buttons
      progress_panel.py  # ProgressPanel(ttk.LabelFrame) -- progress bar + status label
      results_panel.py   # ResultsPanel(ttk.LabelFrame) -- Treeview table + export
    worker.py            # ExtractionWorker -- background thread + queue communication
    dnd.py               # Drag-and-drop abstraction (tkinterdnd2 wrapper with fallback)
```

**Data flow:**
1. User provides files via drag-drop or browse dialog -> `InputPanel` emits file paths
2. `BiExtractorApp` creates an `ExtractionWorker` with the file list
3. `ExtractionWorker` runs in a background `threading.Thread`, calls `engine.discover_files()` then `engine.extract_file()` per file
4. Worker posts progress updates to a `queue.Queue` (file name, index, total, result)
5. `BiExtractorApp` polls the queue via `root.after(100, poll)` and updates `ProgressPanel`
6. On completion, results are passed to `ResultsPanel` which populates the `ttk.Treeview`
7. Export button calls `CsvFormatter.write()` with the collected `ExtractionResult` list

**Key principle:** The GUI never imports from `bi_extractor.cli`. It imports only from `bi_extractor.core.engine`, `bi_extractor.core.models`, `bi_extractor.core.registry`, and `bi_extractor.output.csv_formatter`.

---

## Detailed UI Layout

```
+-----------------------------------------------------------------------+
|  BI Metadata Extractor                                          [_][X] |
+-----------------------------------------------------------------------+
|                                                                        |
|  +-- Input --------------------------------------------------------+  |
|  |                                                                  |  |
|  |  +----------------------------------------------------------+   |  |
|  |  |                                                          |   |  |
|  |  |     Drag files or folders here                           |   |  |
|  |  |     (or use Browse buttons below)                        |   |  |
|  |  |                                                          |   |  |
|  |  +----------------------------------------------------------+   |  |
|  |                                                                  |  |
|  |  [Browse Files...]  [Browse Folder...]    Recursive: [x]         |  |
|  |                                                                  |  |
|  |  Selected: 3 files (.twb, .rdl, .jrxml)                         |  |
|  |                                                                  |  |
|  +------------------------------------------------------------------+  |
|                                                                        |
|  +-- Progress ------------------------------------------------------+  |
|  |                                                                  |  |
|  |  [============================          ] 7 / 12                 |  |
|  |  Processing: SalesReport.twb                                     |  |
|  |                                                                  |  |
|  +------------------------------------------------------------------+  |
|                                                                        |
|  [Extract Metadata]  [Cancel]                          [Clear Results]  |
|                                                                        |
|  +-- Results -------------------------------------------------------+  |
|  |                                                                  |  |
|  |  File Name  | Tool    | Fields | Sources | Elements | Errors     |  |
|  |  -----------+---------+--------+---------+----------+--------    |  |
|  |  Sales.twb  | Tableau |     42 |       3 |       12 |            |  |
|  |  Report.rdl | SSRS    |     18 |       1 |        5 |            |  |
|  |  Inv.jrxml  | Jasper  |     27 |       2 |        8 | 1 warning  |  |
|  |                                                                  |  |
|  |  (click row to expand field-level detail below)                  |  |
|  |                                                                  |  |
|  +------------------------------------------------------------------+  |
|                                                                        |
|  +-- Detail --------------------------------------------------------+  |
|  |                                                                  |  |
|  |  Column Name | Alias    | Type   | Formula | Datasource          |  |
|  |  ------------+----------+--------+---------+-------------        |  |
|  |  Revenue     | Rev      | float  | SUM(...)| SalesDB             |  |
|  |  CustName    | Customer | string |         | SalesDB             |  |
|  |                                                                  |  |
|  +------------------------------------------------------------------+  |
|                                                                        |
|  [Export to CSV...]                                   351 rows total   |
|                                                                        |
+-----------------------------------------------------------------------+
|  Ready.                                                                |
+-----------------------------------------------------------------------+
```

---

## Task Flow

### Task 1: GUI scaffold and application shell
**Files:** `bi_extractor/gui/__init__.py`, `bi_extractor/gui/app.py`

Create the main application window with proper layout management, menu bar, and status bar. Set up the module so it can be launched via `python -m bi_extractor.gui`.

**Details:**

`bi_extractor/gui/__init__.py`:
```python
"""GUI interface for bi-extractor (tkinter/ttk)."""

def launch_gui() -> None:
    """Launch the bi-extractor GUI application."""
    from bi_extractor.gui.app import BiExtractorApp
    app = BiExtractorApp()
    app.mainloop()
```

`bi_extractor/gui/__main__.py`:
```python
"""Allow running the GUI with: python -m bi_extractor.gui"""
from bi_extractor.gui import launch_gui
launch_gui()
```

`bi_extractor/gui/app.py` -- `BiExtractorApp`:
- **Base class:** Uses factory pattern for conditional DnD support:
  ```python
  from bi_extractor.gui.dnd import is_dnd_available
  _Base: type[tk.Tk] = TkinterDnD.Tk if is_dnd_available() else tk.Tk
  class BiExtractorApp(_Base): ...
  ```
- Window title: "BI Metadata Extractor"
- Minimum size: 900x700
- **DPI awareness (Windows):** Call `ctypes.windll.shcore.SetProcessDpiAwareness(1)` in `__init__` for crisp rendering on high-DPI displays
- Uses `ttk.PanedWindow` (vertical) to allow resizing between input/progress area and results area
- Top section: `InputPanel` + `ProgressPanel` + action buttons (Extract, Cancel, Clear)
- Bottom section: `ResultsPanel` (summary table + detail table)
- Status bar at bottom: `ttk.Label` with relief=SUNKEN
- Menu bar with File (Open Files, Open Folder, Export CSV, Exit), View (Clear Results), Help (About, Supported Formats)

**Key methods on `BiExtractorApp`:**
```python
class BiExtractorApp(_Base):
    def __init__(self) -> None: ...
    def _build_menu(self) -> None: ...
    def _build_layout(self) -> None: ...
    def _on_files_selected(self, paths: list[Path]) -> None: ...
    def _start_extraction(self) -> None: ...
    def _poll_worker(self) -> None: ...
    def _on_extraction_complete(self, results: list[ExtractionResult]) -> None: ...
    def _on_extraction_error(self, error: str) -> None: ...
    def _cancel_extraction(self) -> None: ...
    def _export_csv(self) -> None: ...
    def _clear_results(self) -> None: ...
    def _set_status(self, message: str) -> None: ...
    def _show_about(self) -> None: ...
    def _show_formats(self) -> None: ...
```

**Acceptance criteria:**
- Application launches with `python -m bi_extractor.gui` and shows an empty window with correct title, size, and layout frames
- Menu bar is functional (Exit quits, About shows dialog)
- Status bar displays "Ready."

---

### Task 2: Input panel with browse dialogs
**Files:** `bi_extractor/gui/widgets/__init__.py`, `bi_extractor/gui/widgets/input_panel.py`

Build the input panel with file/folder browse buttons, recursive checkbox, and a summary label showing selected files.

**Details:**

`bi_extractor/gui/widgets/input_panel.py` -- `InputPanel(ttk.LabelFrame)`:
```python
class InputPanel(ttk.LabelFrame):
    def __init__(
        self,
        parent: tk.Widget,
        on_files_changed: Callable[[list[Path]], None],
    ) -> None: ...

    def _browse_files(self) -> None: ...
    def _browse_folder(self) -> None: ...
    def _update_summary(self) -> None: ...
    def get_paths(self) -> list[Path]: ...
    def get_recursive(self) -> bool: ...
    def clear(self) -> None: ...
```

- "Browse Files..." button uses `filedialog.askopenfilenames()` with filetypes filter built from `registry.supported_extensions()`
- "Browse Folder..." button uses `filedialog.askdirectory()`
- "Recursive" checkbox (`ttk.Checkbutton` with `tk.BooleanVar`, default=True)
- Summary label: "Selected: N files (.twb, .rdl, ...)" or "Selected: folder 'Reports' (recursive)" or "No files selected"
- Drop zone area: a `tk.Frame` with dashed border (rendered via `highlightbackground`), label text "Drag files or folders here"
- Calls `on_files_changed` callback whenever selection changes
- File type filter string is built dynamically from `get_registry().supported_extensions()`

**Acceptance criteria:**
- Browse Files opens a native file dialog filtered to supported BI file extensions
- Browse Folder opens a native folder picker
- Summary label updates to reflect selection count and extension types
- Recursive checkbox toggles and its state is accessible via `get_recursive()`
- Calling `clear()` resets all state

---

### Task 3: Drag-and-drop support
**Files:** `bi_extractor/gui/dnd.py`

Implement drag-and-drop abstraction with optional `tkinterdnd2` backend and graceful fallback.

**Details:**

`bi_extractor/gui/dnd.py`:
```python
def is_dnd_available() -> bool:
    """Check if tkinterdnd2 is installed."""
    ...

def get_dnd_base_class() -> type[tk.Tk]:
    """Return TkinterDnD.Tk class if available, else tk.Tk.
    Used as base class for BiExtractorApp via factory pattern."""
    ...

def bind_drop(
    widget: tk.Widget,
    callback: Callable[[list[str]], None],
) -> bool:
    """Bind a file drop event to the widget. Returns True if DnD was bound."""
    ...

def parse_drop_data(data: str) -> list[str]:
    """Parse the platform-specific drop data string into file paths."""
    ...
```

- When `tkinterdnd2` is available: `BiExtractorApp` subclasses `TkinterDnD.Tk` instead of `tk.Tk` (handled by `make_dnd_aware`)
- Drop zone in `InputPanel` registers for file drop events via `bind_drop()`
- Drop data parsing handles Windows-style paths (curly-brace-wrapped paths with spaces)
- When `tkinterdnd2` is NOT available: drop zone shows "Install tkinterdnd2 for drag-and-drop support" in muted text, browse buttons remain fully functional
- Add `tkinterdnd2>=0.4` to `[project.optional-dependencies]` as `gui` extra in `pyproject.toml`

**Acceptance criteria:**
- With `tkinterdnd2` installed: dragging a .twb file onto the drop zone adds it to the input list
- With `tkinterdnd2` installed: dragging a folder adds the folder path
- Without `tkinterdnd2`: app launches normally, drop zone shows fallback message, browse buttons work
- `parse_drop_data()` correctly handles Windows paths with spaces

---

### Task 4: Extraction worker with progress reporting
**Files:** `bi_extractor/gui/worker.py`

Build the threaded extraction worker that communicates progress back to the main thread via a queue.

**Details:**

`bi_extractor/gui/worker.py`:
```python
from dataclasses import dataclass
from enum import Enum, auto

class MessageType(Enum):
    DISCOVERY_COMPLETE = auto()
    FILE_START = auto()
    FILE_COMPLETE = auto()
    ALL_COMPLETE = auto()
    ERROR = auto()

@dataclass
class WorkerMessage:
    msg_type: MessageType
    current: int = 0
    total: int = 0
    file_name: str = ""
    result: ExtractionResult | None = None
    error: str = ""

class ExtractionWorker:
    def __init__(
        self,
        paths: list[Path],
        recursive: bool = True,
        message_queue: queue.Queue[WorkerMessage] | None = None,
    ) -> None: ...

    def start(self) -> None:
        """Start extraction in a background thread."""
        ...

    def is_alive(self) -> bool: ...

    def request_cancel(self) -> None:
        """Signal the worker to stop after the current file."""
        ...

    def _run(self) -> None:
        """Worker thread body. Discovers files, extracts each, posts messages."""
        ...
```

- Worker receives a list of `Path` objects (files and/or directories)
- Phase 1: calls `engine.discover_files()` on each directory path, posts `DISCOVERY_COMPLETE` with total count
- Phase 2: iterates through discovered files, calls `engine.extract_file()` on each
  - Posts `FILE_START` before each file (with file name, current index, total)
  - Posts `FILE_COMPLETE` after each file (with `ExtractionResult`)
  - Checks `self._cancel_event` (a `threading.Event`) between files
- Posts `ALL_COMPLETE` when done (includes summary counts)
- Posts `ERROR` if an unexpected exception occurs in the thread
- Thread is daemon=True so it does not prevent app exit

**Polling in `BiExtractorApp._poll_worker()` (fixes: error recovery, termination race, double-start):**
```python
def _start_extraction(self) -> None:
    # Double-start protection
    if self._worker and self._worker.is_alive():
        return
    # Disable Extract, enable Cancel, disable browse/DnD during extraction
    ...

def _poll_worker(self) -> None:
    try:
        while True:
            msg = self._worker_queue.get_nowait()
            if msg.msg_type == MessageType.DISCOVERY_COMPLETE:
                if msg.total == 0:
                    self._set_status("No supported BI files found in selected path(s).")
                    self._on_extraction_error("")  # Reset UI without error dialog
                    return
                self._progress_panel.set_total(msg.total)
            elif msg.msg_type == MessageType.FILE_START:
                self._progress_panel.set_current(msg.current, msg.file_name)
            elif msg.msg_type == MessageType.FILE_COMPLETE:
                self._results.append(msg.result)
            elif msg.msg_type == MessageType.ALL_COMPLETE:
                self._on_extraction_complete(self._results)
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

def _on_extraction_error(self, error: str) -> None:
    """Re-enable UI and show error -- symmetric with _on_extraction_complete."""
    self._extract_btn.config(state=tk.NORMAL)
    self._cancel_btn.config(state=tk.DISABLED)
    self._progress_panel.reset()
    if error:
        messagebox.showerror("Extraction Error", error)
    self._set_status("Extraction failed.")

def _drain_remaining_messages(self) -> None:
    """Process any messages left in the queue after the worker thread exits."""
    try:
        while True:
            msg = self._worker_queue.get_nowait()
            if msg.msg_type == MessageType.ALL_COMPLETE:
                self._on_extraction_complete(self._results)
                return
            elif msg.msg_type == MessageType.FILE_COMPLETE:
                self._results.append(msg.result)
    except queue.Empty:
        # Worker finished without ALL_COMPLETE -- show partial results
        if self._results:
            self._on_extraction_complete(self._results)
```

**Acceptance criteria:**
- Extraction runs in a background thread; UI remains responsive (no freezing)
- Progress messages arrive in correct order: DISCOVERY_COMPLETE, then FILE_START/FILE_COMPLETE pairs, then ALL_COMPLETE
- Cancel button sets cancel event; worker stops after current file and posts ALL_COMPLETE with partial results
- Worker handles exceptions gracefully (posts ERROR message, does not crash thread silently)

---

### Task 5: Progress panel
**Files:** `bi_extractor/gui/widgets/progress_panel.py`

Build the progress bar and status label that visualize extraction progress.

**Details:**

`bi_extractor/gui/widgets/progress_panel.py` -- `ProgressPanel(ttk.LabelFrame)`:
```python
class ProgressPanel(ttk.LabelFrame):
    def __init__(self, parent: tk.Widget) -> None: ...

    def set_total(self, total: int) -> None:
        """Set total file count and reset progress bar."""
        ...

    def set_current(self, current: int, file_name: str) -> None:
        """Update progress bar position and status label."""
        ...

    def set_complete(self, success_count: int, error_count: int) -> None:
        """Show completion message."""
        ...

    def set_indeterminate(self, message: str) -> None:
        """Switch to indeterminate mode (for discovery phase)."""
        ...

    def reset(self) -> None:
        """Reset to initial state."""
        ...
```

- `ttk.Progressbar` in determinate mode (maximum=total, value=current)
- During discovery phase: indeterminate mode with "Discovering files..."
- Status label: "Processing file 7 of 12: SalesReport.twb"
- Completion label: "Complete: 11 extracted, 1 error"
- Counter label: "7 / 12" right-aligned next to progress bar

**Acceptance criteria:**
- Progress bar advances smoothly from 0 to total
- Status label shows current file name during extraction
- Indeterminate mode displays correctly during discovery phase
- `reset()` returns progress bar and labels to initial empty state

---

### Task 6: Results panel with metadata table viewer
**Files:** `bi_extractor/gui/widgets/results_panel.py`

Build the two-level results viewer: summary table (one row per file) and detail table (fields for selected file).

**Details:**

`bi_extractor/gui/widgets/results_panel.py` -- `ResultsPanel(ttk.LabelFrame)`:
```python
class ResultsPanel(ttk.LabelFrame):
    def __init__(
        self,
        parent: tk.Widget,
        on_row_count_changed: Callable[[int], None] | None = None,
    ) -> None: ...

    def add_result(self, result: ExtractionResult) -> None:
        """Add a single extraction result to the summary table."""
        ...

    def set_results(self, results: list[ExtractionResult]) -> None:
        """Replace all results."""
        ...

    def clear(self) -> None:
        """Clear both summary and detail tables."""
        ...

    def get_results(self) -> list[ExtractionResult]:
        """Return all stored results (for export)."""
        ...

    def _on_summary_select(self, event: tk.Event) -> None:
        """Handle click on summary row -- populate detail table."""
        ...

    def _sort_by_column(self, tree: ttk.Treeview, col: str, reverse: bool) -> None:
        """Sort treeview by clicking column header."""
        ...

    def _build_summary_tree(self) -> ttk.Treeview: ...
    def _build_detail_tree(self) -> ttk.Treeview: ...
```

**Summary table columns** (top Treeview):
| Column | Source |
|--------|--------|
| File Name | `Path(result.source_file).name` |
| Tool | `result.tool_name` |
| File Type | `result.file_type` |
| Fields | `len(result.fields)` |
| Datasources | `len(result.datasources)` |
| Elements | `len(result.report_elements)` |
| Parameters | `len(result.parameters)` |
| Relationships | `len(result.relationships)` |
| Filters | `len(result.filters)` |
| Errors | `len(result.errors)` -- red text if > 0 |

**Detail table columns** (bottom Treeview, populated on summary row click):
| Column | Source |
|--------|--------|
| Column Name | `field.name` |
| Alias | `field.alias` |
| Data Type | `field.data_type` |
| Role | `field.role` |
| Field Type | `field.field_type` |
| Formula | `field.formula` (truncated to 80 chars with "..." tooltip) |
| Datasource | `field.datasource` |

**Additional features:**
- Both Treeviews have vertical scrollbars
- Column headers are clickable for sorting (ascending/descending toggle)
- Error rows in summary table use a tag with red foreground
- Selecting a row in summary populates detail table with that file's fields
- Tooltip on formula cells shows full formula text (using a simple `tk.Toplevel` tooltip)
- `ttk.PanedWindow` (vertical) separates summary and detail tables for resizable split

**Acceptance criteria:**
- Summary table shows one row per extracted file with correct metadata counts
- Clicking a summary row populates the detail table with that file's fields
- Column sorting works on all columns (numeric sort for count columns, alpha for text)
- Error rows display with red text
- Scrollbars appear when content exceeds visible area
- Export returns all stored `ExtractionResult` objects

---

## Detailed TODOs

### TODO 1: Create GUI module scaffold and application shell
**Acceptance:** `python -m bi_extractor.gui` launches a window with title "BI Metadata Extractor", correct minimum size (900x700), menu bar (File/View/Help), empty panel placeholders, and status bar showing "Ready."

**Files to create:**
- `bi_extractor/gui/__init__.py` (update existing)
- `bi_extractor/gui/__main__.py` (new)
- `bi_extractor/gui/app.py` (new)
- `bi_extractor/gui/widgets/__init__.py` (new)

**Implementation notes:**
- `BiExtractorApp.__init__()` sets title, geometry, minsize, protocol("WM_DELETE_WINDOW", self.destroy)
- Use `self.columnconfigure(0, weight=1)` and `self.rowconfigure()` for responsive grid layout
- Menu bar: `tk.Menu(self)` with File, View, Help cascades
- Status bar: `ttk.Label(self, text="Ready.", relief=tk.SUNKEN, anchor=tk.W)`

---

### TODO 2: Implement InputPanel with browse dialogs
**Acceptance:** Browse Files opens a file dialog filtered to supported extensions, Browse Folder opens a directory picker, summary label shows "Selected: N files (.ext1, .ext2)" after selection, Recursive checkbox is functional.

**Files to create:**
- `bi_extractor/gui/widgets/input_panel.py` (new)

**Implementation notes:**
- Build filetypes list from `get_registry().supported_extensions()` at panel init time
- Format: `[("BI Report Files", "*.twb *.twbx *.rdl ..."), ("All Files", "*.*")]`
- Pass `initialdir=Path.cwd()` to file dialogs for a consistent first-launch experience
- Drop zone frame: `tk.Frame` with `highlightbackground="#999"`, `highlightthickness=2`, centered label
- Store selected paths in `self._paths: list[Path]`
- Call `self._on_files_changed(self._paths)` after any selection change

---

### TODO 3: Implement drag-and-drop abstraction
**Acceptance:** With `tkinterdnd2` installed, dragging files onto the drop zone adds them to the input list. Without it, the app launches normally with a fallback message.

**Files to create:**
- `bi_extractor/gui/dnd.py` (new)

**Files to modify:**
- `pyproject.toml` -- add `gui = ["tkinterdnd2>=0.4"]` to `[project.optional-dependencies]`
- `bi_extractor/gui/app.py` -- conditional `TkinterDnD.Tk` vs `tk.Tk` based on `dnd.is_dnd_available()`
- `bi_extractor/gui/widgets/input_panel.py` -- call `dnd.bind_drop()` on drop zone frame

**Implementation notes:**
- `is_dnd_available()`: try `import tkinterdnd2` in a try/except ImportError
- `get_dnd_base_class()`: returns `TkinterDnD.Tk` class if available, else `tk.Tk` class (used by BiExtractorApp as its base class via factory pattern)
- `parse_drop_data()`: handle `{C:/path with spaces/file.twb}` brace wrapping on Windows, UNC paths (`\\server\share\file.twb`), and multiple files separated by spaces
- `bind_drop()`: register `"<<Drop>>"` event, parse data, filter to supported extensions, call callback

---

### TODO 4: Implement ExtractionWorker with progress queue
**Acceptance:** Extraction runs in a daemon background thread, posts WorkerMessage objects to a queue in correct sequence, UI polls via `after()` and remains responsive, cancel stops after current file.

**Files to create:**
- `bi_extractor/gui/worker.py` (new)

**Implementation notes:**
- `ExtractionWorker.__init__()` stores paths, creates `queue.Queue()`, creates `threading.Event()` for cancel
- `_run()` method is the thread target:
  1. For each path: if directory, call `discover_files(path, recursive=self._recursive)`; if file, add directly
  2. Post `DISCOVERY_COMPLETE` with total count
  3. For each file: check cancel event, post `FILE_START`, call `extract_file()`, post `FILE_COMPLETE`
  4. Post `ALL_COMPLETE`
- Wrap entire `_run()` in try/except to post `ERROR` on unexpected failures
- `start()`: creates `threading.Thread(target=self._run, daemon=True)` and starts it

---

### TODO 5: Implement ProgressPanel
**Acceptance:** Progress bar advances from 0 to total during extraction, shows indeterminate mode during discovery, status label shows current file name, completion shows success/error counts.

**Files to create:**
- `bi_extractor/gui/widgets/progress_panel.py` (new)

**Implementation notes:**
- `ttk.Progressbar(self, orient=tk.HORIZONTAL, mode="determinate")` with `self._progress_var = tk.DoubleVar()`
- `set_indeterminate()`: switch to mode="indeterminate", call `self._bar.start(10)`
- `set_total()`: switch to mode="determinate", set maximum
- `set_current()`: update value and label text
- `set_complete()`: stop bar, set to maximum, update label with summary

---

### TODO 6: Implement ResultsPanel with summary and detail Treeviews
**Acceptance:** Summary table shows one row per file with metadata counts, clicking a row populates the detail table with field-level data, column sorting works, error rows are red, scrollbars functional, export returns all results.

**Files to create:**
- `bi_extractor/gui/widgets/results_panel.py` (new)

**Implementation notes:**
- Summary Treeview: `ttk.Treeview(columns=(...), show="headings")`
- Detail Treeview: same pattern, populated on `<<TreeviewSelect>>` event
- Column sorting: bind `heading` command to `_sort_by_column()`, toggle reverse flag per column
- Numeric sort: for Fields/Datasources/etc columns, convert to int for comparison
- Error tag: `self._summary_tree.tag_configure("error", foreground="red")`
- Formula tooltip: bind `<Enter>`/`<Leave>` on detail tree, show `tk.Toplevel` with full formula text
- Store results in `self._results: list[ExtractionResult]` indexed by tree item ID
- `ttk.PanedWindow(orient=tk.VERTICAL)` separates the two trees
- **Treeview performance (review fix):** For detail table batch insertion, disable widget updates during population (e.g., `tree.config(height=0)` or detach/reattach pattern). For files with 2000+ fields, show first 2000 rows with a "Show all N fields..." button to avoid Treeview sluggishness.

---

### TODO 7: Wire everything together and add export
**Acceptance:** End-to-end flow works: browse files -> click Extract -> progress updates -> results appear in table -> click Export to CSV -> file saved. All menu items functional. Clear Results resets everything.

**Files to modify:**
- `bi_extractor/gui/app.py` -- integrate all panels, wire callbacks, implement polling loop

**Implementation notes:**
- `_start_extraction()`: disable Extract button, create `ExtractionWorker`, call `start()`, begin `_poll_worker()`
- `_poll_worker()`: drain queue, update progress panel, accumulate results, re-schedule via `after(100)`
- `_on_extraction_complete()`: re-enable Extract button, update status bar with summary, call `_results_panel.set_results()`
- `_export_csv()`: open `filedialog.asksaveasfilename()` with default name "BI_Metadata.csv". Split chosen path: `CsvFormatter().write(results, chosen.parent, filename=chosen.name)`. Wrap in try/except OSError for disk-full handling.
- `_clear_results()`: clear results panel, reset progress panel, update status bar
- `_show_formats()`: call `get_registry().list_parsers()`, display in a messagebox or simple dialog
- Wire `InputPanel.on_files_changed` to enable/disable Extract button based on selection

---

### TODO 8: Add entry point and update pyproject.toml
**Acceptance:** `bi-extractor-gui` command launches the GUI. `pip install -e .[gui]` installs tkinterdnd2 for drag-drop. All existing tests pass. mypy strict passes on new code.

**Files to modify:**
- `pyproject.toml` -- add gui script entry point and optional dependency

**Changes:**
```toml
[project.scripts]
bi-extractor = "bi_extractor.cli.main:main"
bi-extractor-gui = "bi_extractor.gui:launch_gui"

[project.optional-dependencies]
gui = ["tkinterdnd2>=0.4"]
```

- Ensure `bi_extractor/gui/py.typed` marker exists if needed for mypy
- Run `mypy bi_extractor/gui/` to verify strict compliance
- Run `pytest` to verify no existing tests break

---

### TODO 9: Add GUI tests
**Acceptance:** Tests verify worker logic, data flow, and panel state management without requiring a display (headless-compatible where possible).

**Files to create:**
- `tests/test_gui_worker.py` (new)
- `tests/test_gui_results.py` (new -- optional, display-dependent)

**Testing strategy:**
- **Worker tests** (headless, no tkinter required):
  - Test `ExtractionWorker` with real fixture files from `tests/fixtures/`
  - Verify message sequence: DISCOVERY_COMPLETE -> FILE_START/FILE_COMPLETE pairs -> ALL_COMPLETE
  - Verify cancel behavior: set cancel event, check ALL_COMPLETE arrives with partial results
  - Verify error handling: pass non-existent path, check ERROR message
- **Results panel data tests** (headless if possible, skip on CI if no display):
  - Test `_sort_by_column` logic extracted as a pure function
  - Test `parse_drop_data()` with various Windows path formats: brace-wrapped (`{C:\path with spaces\file.twb}`), no braces, UNC paths (`\\server\share\file.twb`), multiple files separated by spaces
- **Manual test script** (`tests/manual_gui_test.py`, not in pytest suite):
  - Launch GUI with test fixtures pre-loaded
  - Checklist for manual verification

---

## Success Criteria

1. `python -m bi_extractor.gui` launches a functional GUI on Windows with Python 3.10+
2. Users can select files via browse dialog OR drag-and-drop (when tkinterdnd2 installed)
3. Extraction shows real-time progress bar and per-file status messages
4. Results display in a sortable, scrollable table with summary and detail views
5. Export to CSV produces identical output to CLI `extract` command
6. UI remains responsive during extraction (no freezing)
7. All 351 existing tests continue to pass
8. mypy strict passes on all new GUI code
9. No changes to `bi_extractor/core/`, `bi_extractor/parsers/`, `bi_extractor/cli/`, or `bi_extractor/output/`

---

## File Summary

| Action | File Path |
|--------|-----------|
| Modify | `bi_extractor/gui/__init__.py` |
| Create | `bi_extractor/gui/__main__.py` |
| Create | `bi_extractor/gui/app.py` |
| Create | `bi_extractor/gui/dnd.py` |
| Create | `bi_extractor/gui/worker.py` |
| Create | `bi_extractor/gui/widgets/__init__.py` |
| Create | `bi_extractor/gui/widgets/input_panel.py` |
| Create | `bi_extractor/gui/widgets/progress_panel.py` |
| Create | `bi_extractor/gui/widgets/results_panel.py` |
| Modify | `pyproject.toml` |
| Create | `tests/test_gui_worker.py` |
| Create | `tests/test_gui_results.py` |

**Total: 12 files (10 new, 2 modified)**

---

## Review Fixes Applied (Architect + Critic Consensus)

The following issues were identified during the Architect and Critic review cycle and have been incorporated into the plan above:

| # | Issue | Fix Applied |
|---|-------|-------------|
| 1 | CsvFormatter.write() takes directory + filename, not a file path | Split `filedialog` result: `chosen.parent` + `chosen.name`. Wrap in try/except OSError. |
| 2 | tkinterdnd2 base class can't be conditionally inherited at runtime | Factory pattern: `_Base = get_dnd_base_class()` then `class BiExtractorApp(_Base)` |
| 3 | ERROR handler in polling loop doesn't re-enable Extract button | Added `_on_extraction_error()` method symmetric with `_on_extraction_complete()` |
| 4 | Polling termination race (worker finishes between queue drain and is_alive check) | Added `_drain_remaining_messages()` called after `is_alive()` returns False |
| 5 | Missing Cancel button in UI layout | Added Cancel button between Extract and Clear; enables during extraction |
| 6 | Double-start protection missing | Guard `_start_extraction()` with `if self._worker and self._worker.is_alive(): return` |
| 7 | DPI awareness for Windows high-DPI displays | Added `ctypes.windll.shcore.SetProcessDpiAwareness(1)` in app init |
| 8 | Treeview performance for large field counts | Batch insert with updates disabled; row limit (2000) with "Show all" button for detail table |
| 9 | Empty results not handled | Show "No supported BI files found" when discovery returns 0 files |
| 10 | Missing Filters column in summary table | Added `len(result.filters)` column |
| 11 | `parse_drop_data()` edge cases underspecified | Added UNC paths, brace-wrapped, and multi-file test cases |
| 12 | File dialogs lack initialdir | Added `initialdir=Path.cwd()` to browse dialogs |
