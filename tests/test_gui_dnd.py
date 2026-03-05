"""Tests for drag-and-drop data parsing (pure function, no display needed)."""

from __future__ import annotations

import pytest

from bi_extractor.gui.dnd import is_dnd_available, parse_drop_data


class TestParseDropData:
    """Test parse_drop_data with various Windows path formats."""

    def test_single_path_no_spaces(self) -> None:
        """Simple path without spaces."""
        result = parse_drop_data("C:/Users/report.twb")
        assert result == ["C:/Users/report.twb"]

    def test_single_path_brace_wrapped(self) -> None:
        """Brace-wrapped path with spaces (Windows DnD format)."""
        result = parse_drop_data("{C:/Users/My Reports/report.twb}")
        assert result == ["C:/Users/My Reports/report.twb"]

    def test_multiple_paths_no_spaces(self) -> None:
        """Multiple paths separated by spaces."""
        result = parse_drop_data("C:/a/file1.twb C:/b/file2.rdl")
        assert result == ["C:/a/file1.twb", "C:/b/file2.rdl"]

    def test_multiple_paths_mixed(self) -> None:
        """Mix of brace-wrapped and plain paths."""
        data = "{C:/My Reports/sales.twb} C:/other/report.rdl"
        result = parse_drop_data(data)
        assert result == ["C:/My Reports/sales.twb", "C:/other/report.rdl"]

    def test_unc_path(self) -> None:
        """UNC network path."""
        result = parse_drop_data("\\\\server\\share\\report.twb")
        assert result == ["\\\\server\\share\\report.twb"]

    def test_unc_path_brace_wrapped(self) -> None:
        """Brace-wrapped UNC path with spaces."""
        result = parse_drop_data("{\\\\server\\My Share\\report.twb}")
        assert result == ["\\\\server\\My Share\\report.twb"]

    def test_empty_string(self) -> None:
        """Empty input returns empty list."""
        assert parse_drop_data("") == []

    def test_whitespace_only(self) -> None:
        """Whitespace-only input returns empty list."""
        assert parse_drop_data("   ") == []

    def test_multiple_brace_wrapped(self) -> None:
        """Multiple brace-wrapped paths."""
        data = "{C:/path one/a.twb} {C:/path two/b.rdl}"
        result = parse_drop_data(data)
        assert result == ["C:/path one/a.twb", "C:/path two/b.rdl"]

    def test_forward_slashes(self) -> None:
        """Forward slashes in paths."""
        result = parse_drop_data("C:/Users/reyno/Documents/report.twb")
        assert result == ["C:/Users/reyno/Documents/report.twb"]

    def test_backslashes(self) -> None:
        """Backslashes in paths."""
        result = parse_drop_data("C:\\Users\\reyno\\report.twb")
        assert result == ["C:\\Users\\reyno\\report.twb"]


class TestIsDndAvailable:
    """Test DnD availability check."""

    def test_returns_bool(self) -> None:
        """is_dnd_available always returns a boolean."""
        result = is_dnd_available()
        assert isinstance(result, bool)
