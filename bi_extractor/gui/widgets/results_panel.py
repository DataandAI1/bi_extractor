"""Results panel with summary and detail Treeview tables."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Callable

from bi_extractor.core.models import ExtractionResult

# Maximum rows in detail table before truncation
_DETAIL_ROW_LIMIT = 2000


class _Tooltip:
    """Simple hover tooltip for Treeview cells."""

    def __init__(self, widget: tk.Widget) -> None:
        self._widget = widget
        self._tipwindow: tk.Toplevel | None = None
        self._text = ""

    def show(self, text: str, x: int, y: int) -> None:
        """Display tooltip near the given screen coordinates."""
        if not text or self._tipwindow:
            return
        self._text = text
        self._tipwindow = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x + 15}+{y + 10}")
        label = tk.Label(
            tw,
            text=text,
            justify=tk.LEFT,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            font=("TkDefaultFont", 9),
            wraplength=500,
        )
        label.pack()

    def hide(self) -> None:
        """Hide the tooltip."""
        tw = self._tipwindow
        self._tipwindow = None
        if tw:
            tw.destroy()


class ResultsPanel(ttk.LabelFrame):
    """Two-level results viewer: summary table and field-level detail table."""

    # Summary table column definitions: (id, heading, width, anchor)
    _SUMMARY_COLS: list[tuple[str, str, int, str]] = [
        ("file_name", "File Name", 180, "w"),
        ("tool", "Tool", 100, "w"),
        ("file_type", "File Type", 70, "center"),
        ("fields", "Fields", 60, "center"),
        ("datasources", "Datasources", 85, "center"),
        ("elements", "Elements", 75, "center"),
        ("parameters", "Parameters", 80, "center"),
        ("relationships", "Relationships", 90, "center"),
        ("filters", "Filters", 60, "center"),
        ("errors", "Errors", 60, "center"),
    ]

    # Detail table column definitions
    _DETAIL_COLS: list[tuple[str, str, int, str]] = [
        ("name", "Column Name", 160, "w"),
        ("alias", "Alias", 130, "w"),
        ("data_type", "Data Type", 90, "w"),
        ("role", "Role", 80, "w"),
        ("field_type", "Field Type", 100, "w"),
        ("formula", "Formula", 250, "w"),
        ("datasource", "Datasource", 140, "w"),
    ]

    # Numeric columns for sorting
    _NUMERIC_COLS = {"fields", "datasources", "elements", "parameters",
                     "relationships", "filters", "errors"}

    def __init__(
        self,
        parent: tk.Widget,
        on_row_count_changed: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(parent, text="Results", padding=5)
        self._on_row_count_changed = on_row_count_changed
        self._results: list[ExtractionResult] = []
        self._result_by_item: dict[str, ExtractionResult] = {}
        self._sort_reverse: dict[str, bool] = {}
        self._tooltip = _Tooltip(self)
        self._truncated = False
        self._build_ui()

    def _build_ui(self) -> None:
        """Build the results panel with summary and detail Treeviews."""
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Summary table
        summary_frame = ttk.Frame(paned)
        paned.add(summary_frame, weight=1)

        col_ids = [c[0] for c in self._SUMMARY_COLS]
        self._summary_tree = ttk.Treeview(
            summary_frame, columns=col_ids, show="headings", height=6
        )

        for col_id, heading, width, anchor in self._SUMMARY_COLS:
            self._summary_tree.heading(
                col_id,
                text=heading,
                command=lambda c=col_id: self._sort_by_column(  # type: ignore[misc]
                    self._summary_tree, c
                ),
            )
            self._summary_tree.column(col_id, width=width, anchor=anchor)

        self._summary_tree.tag_configure("error", foreground="red")
        self._summary_tree.bind("<<TreeviewSelect>>", self._on_summary_select)

        summary_scroll = ttk.Scrollbar(
            summary_frame, orient=tk.VERTICAL, command=self._summary_tree.yview
        )
        self._summary_tree.configure(yscrollcommand=summary_scroll.set)
        self._summary_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        summary_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Detail table
        detail_frame = ttk.Frame(paned)
        paned.add(detail_frame, weight=2)

        # Detail header with optional truncation notice
        self._detail_header = ttk.Frame(detail_frame)
        self._detail_header.pack(fill=tk.X)

        self._detail_title = ttk.Label(
            self._detail_header, text="Select a file above to view field details"
        )
        self._detail_title.pack(side=tk.LEFT)

        self._truncation_label = ttk.Label(
            self._detail_header, text="", foreground="orange"
        )
        self._truncation_label.pack(side=tk.RIGHT)

        detail_col_ids = [c[0] for c in self._DETAIL_COLS]
        self._detail_tree = ttk.Treeview(
            detail_frame, columns=detail_col_ids, show="headings", height=8
        )

        for col_id, heading, width, anchor in self._DETAIL_COLS:
            self._detail_tree.heading(
                col_id,
                text=heading,
                command=lambda c=col_id: self._sort_by_column(  # type: ignore[misc]
                    self._detail_tree, c
                ),
            )
            self._detail_tree.column(col_id, width=width, anchor=anchor)

        detail_scroll = ttk.Scrollbar(
            detail_frame, orient=tk.VERTICAL, command=self._detail_tree.yview
        )
        self._detail_tree.configure(yscrollcommand=detail_scroll.set)
        self._detail_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Tooltip bindings for formula column
        self._detail_tree.bind("<Motion>", self._on_detail_motion)
        self._detail_tree.bind("<Leave>", self._on_detail_leave)

    def add_result(self, result: ExtractionResult) -> None:
        """Add a single extraction result to the summary table."""
        self._results.append(result)
        self._insert_summary_row(result)
        if self._on_row_count_changed:
            self._on_row_count_changed(self._total_field_count())

    def set_results(self, results: list[ExtractionResult]) -> None:
        """Replace all results and rebuild the summary table."""
        self._results = list(results)
        self._result_by_item.clear()
        self._summary_tree.delete(*self._summary_tree.get_children())
        self._clear_detail()

        for result in self._results:
            self._insert_summary_row(result)

        if self._on_row_count_changed:
            self._on_row_count_changed(self._total_field_count())

    def clear(self) -> None:
        """Clear both summary and detail tables."""
        self._results.clear()
        self._result_by_item.clear()
        self._summary_tree.delete(*self._summary_tree.get_children())
        self._clear_detail()
        if self._on_row_count_changed:
            self._on_row_count_changed(0)

    def get_results(self) -> list[ExtractionResult]:
        """Return all stored results (for export)."""
        return list(self._results)

    def _insert_summary_row(self, result: ExtractionResult) -> None:
        """Insert one row into the summary Treeview."""
        error_count = len(result.errors)
        values = (
            Path(result.source_file).name,
            result.tool_name,
            result.file_type,
            len(result.fields),
            len(result.datasources),
            len(result.report_elements),
            len(result.parameters),
            len(result.relationships),
            len(result.filters),
            error_count,
        )
        tags = ("error",) if error_count > 0 else ()
        item_id = self._summary_tree.insert("", tk.END, values=values, tags=tags)
        self._result_by_item[item_id] = result

    def _on_summary_select(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Handle click on summary row — populate detail table."""
        selection = self._summary_tree.selection()
        if not selection:
            return

        item_id = selection[0]
        result = self._result_by_item.get(item_id)
        if result is None:
            return

        self._populate_detail(result)

    def _populate_detail(self, result: ExtractionResult) -> None:
        """Fill the detail table with fields from the selected result."""
        self._clear_detail()

        file_name = Path(result.source_file).name
        total_fields = len(result.fields)
        self._detail_title.config(text=f"Fields for: {file_name}")

        # Limit rows for performance
        fields = result.fields
        if total_fields > _DETAIL_ROW_LIMIT:
            fields = result.fields[:_DETAIL_ROW_LIMIT]
            self._truncated = True
            self._truncation_label.config(
                text=f"Showing {_DETAIL_ROW_LIMIT} of {total_fields} fields"
            )
        else:
            self._truncated = False
            self._truncation_label.config(text="")

        for field in fields:
            formula_display = field.formula
            if len(formula_display) > 80:
                formula_display = formula_display[:77] + "..."

            values = (
                field.name,
                field.alias,
                field.data_type,
                field.role,
                field.field_type,
                formula_display,
                field.datasource,
            )
            self._detail_tree.insert("", tk.END, values=values)

    def _clear_detail(self) -> None:
        """Clear the detail table."""
        self._detail_tree.delete(*self._detail_tree.get_children())
        self._detail_title.config(text="Select a file above to view field details")
        self._truncation_label.config(text="")
        self._truncated = False
        self._tooltip.hide()

    def _sort_by_column(self, tree: ttk.Treeview, col: str) -> None:
        """Sort treeview by clicking column header."""
        key = f"{id(tree)}_{col}"
        reverse = self._sort_reverse.get(key, False)

        items = [(tree.set(item, col), item) for item in tree.get_children("")]

        # Numeric sort for count columns
        if col in self._NUMERIC_COLS:
            items.sort(key=lambda t: int(t[0]) if t[0].isdigit() else 0,
                       reverse=reverse)
        else:
            items.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for index, (_, item) in enumerate(items):
            tree.move(item, "", index)

        self._sort_reverse[key] = not reverse

    def _on_detail_motion(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Show tooltip for formula column on hover."""
        self._tooltip.hide()

        region = self._detail_tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        col = self._detail_tree.identify_column(event.x)
        # Column #6 is formula (0-indexed in identify is #1-based)
        if col != "#6":
            return

        item = self._detail_tree.identify_row(event.y)
        if not item:
            return

        # Find the original result and field to get full formula
        selection = self._summary_tree.selection()
        if not selection:
            return

        result = self._result_by_item.get(selection[0])
        if result is None:
            return

        # Get row index in detail tree
        children = self._detail_tree.get_children("")
        try:
            row_idx = list(children).index(item)
        except ValueError:
            return

        if row_idx < len(result.fields):
            formula = result.fields[row_idx].formula
            if formula and len(formula) > 80:
                self._tooltip.show(formula, event.x_root, event.y_root)

    def _on_detail_leave(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Hide tooltip when mouse leaves the detail tree."""
        self._tooltip.hide()

    def _total_field_count(self) -> int:
        """Count total fields across all results."""
        return sum(len(r.fields) for r in self._results)
