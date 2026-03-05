"""GUI interface for bi-extractor (tkinter/ttk)."""

from __future__ import annotations


def launch_gui() -> None:
    """Launch the bi-extractor GUI application."""
    from bi_extractor.gui.app import BiExtractorApp

    app = BiExtractorApp()
    app.mainloop()
