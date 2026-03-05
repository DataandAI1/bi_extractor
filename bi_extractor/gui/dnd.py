"""Drag-and-drop abstraction with optional tkinterdnd2 backend.

Provides graceful fallback when tkinterdnd2 is not installed — browse
dialogs remain fully functional, and the drop zone shows a hint to
install the optional dependency.
"""

from __future__ import annotations

import re
import tkinter as tk
from typing import Callable


def is_dnd_available() -> bool:
    """Check if tkinterdnd2 is installed and usable."""
    try:
        import tkinterdnd2  # noqa: F401

        return True
    except ImportError:
        return False


def get_dnd_base_class() -> type[tk.Tk]:
    """Return TkinterDnD.Tk class if available, else tk.Tk.

    Used as base class for BiExtractorApp via factory pattern::

        _Base = get_dnd_base_class()
        class BiExtractorApp(_Base): ...
    """
    if is_dnd_available():
        from tkinterdnd2 import TkinterDnD  # type: ignore[import-untyped]

        return TkinterDnD.Tk  # type: ignore[no-any-return]
    return tk.Tk


def bind_drop(
    widget: tk.Widget,
    callback: Callable[[list[str]], None],
) -> bool:
    """Bind a file drop event to the widget.

    Returns True if DnD was successfully bound, False if tkinterdnd2
    is not available.
    """
    if not is_dnd_available():
        return False

    try:
        from tkinterdnd2 import DND_FILES  # type: ignore[import-untyped]

        widget.drop_target_register(DND_FILES)  # type: ignore[attr-defined]

        def _on_drop(event: object) -> None:
            data = getattr(event, "data", "")
            paths = parse_drop_data(str(data))
            if paths:
                callback(paths)

        widget.dnd_bind("<<Drop>>", _on_drop)  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def parse_drop_data(data: str) -> list[str]:
    """Parse platform-specific drop data string into file paths.

    Handles Windows-style paths including:
    - Brace-wrapped paths with spaces: ``{C:/path with spaces/file.twb}``
    - Simple paths without spaces: ``C:/path/file.twb``
    - UNC paths: ``\\\\server\\share\\file.twb``
    - Multiple files separated by spaces
    """
    if not data or not data.strip():
        return []

    paths: list[str] = []

    # Match brace-wrapped paths first, then unbraced tokens
    pattern = r"\{([^}]+)\}|(\S+)"
    for match in re.finditer(pattern, data):
        path = match.group(1) or match.group(2)
        if path:
            # Normalize forward slashes to OS-appropriate separators
            paths.append(path.strip())

    return paths
