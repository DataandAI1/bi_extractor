"""Tests for the bi-extractor CLI interface."""

from __future__ import annotations

import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bi_extractor.cli.main import (
    _build_parser,
    _configure_logging,
    _parse_extensions,
    _render_table,
    main,
)


# ---------------------------------------------------------------------------
# _render_table
# ---------------------------------------------------------------------------

class TestRenderTable:
    def test_basic_table(self) -> None:
        headers = ["Name", "Value"]
        rows = [["foo", "bar"], ["longer_name", "x"]]
        result = _render_table(headers, rows)
        lines = result.splitlines()
        # Should have: sep, header, sep, row1, row2, sep = 6 lines
        assert len(lines) == 6
        assert "Name" in lines[1]
        assert "Value" in lines[1]
        assert "foo" in lines[3]
        assert "longer_name" in lines[4]

    def test_column_widths_expand_to_data(self) -> None:
        headers = ["A"]
        rows = [["very_long_value"]]
        result = _render_table(headers, rows)
        assert "very_long_value" in result

    def test_empty_rows(self) -> None:
        headers = ["Col1", "Col2"]
        rows: list[list[str]] = []
        result = _render_table(headers, rows)
        # sep, header, sep, newline = 4 lines (including trailing newline if used, but let's check exact count)
        assert result.count("\n") == 3


# ---------------------------------------------------------------------------
# _parse_extensions
# ---------------------------------------------------------------------------

class TestParseExtensions:
    def test_none_input_returns_none(self) -> None:
        assert _parse_extensions(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert _parse_extensions("") is None

    def test_single_extension(self) -> None:
        result = _parse_extensions("twb")
        assert result == {".twb"}

    def test_multiple_extensions(self) -> None:
        result = _parse_extensions("twb,pbix,rdl")
        assert result == {".twb", ".pbix", ".rdl"}

    def test_strips_leading_dot(self) -> None:
        result = _parse_extensions(".twb,.pbix")
        assert result == {".twb", ".pbix"}

    def test_normalizes_to_lowercase(self) -> None:
        result = _parse_extensions("TWB,PBIX")
        assert result == {".twb", ".pbix"}

    def test_strips_spaces(self) -> None:
        result = _parse_extensions("twb, pbix , rdl")
        assert result == {".twb", ".pbix", ".rdl"}


# ---------------------------------------------------------------------------
# Argument parser — extract subcommand
# ---------------------------------------------------------------------------

class TestExtractSubcommand:
    def _parse(self, args: list[str]) -> object:
        parser = _build_parser()
        return parser.parse_args(args)

    def test_minimal_invocation(self) -> None:
        ns = self._parse(["extract", "/some/path"])
        assert ns.input_path == "/some/path"
        assert ns.output is None
        assert ns.format == "csv"
        assert ns.recursive is True
        assert ns.types is None
        assert ns.verbose is False
        assert ns.quiet is False
        assert ns.sanitize == "passwords"

    def test_output_short_flag(self) -> None:
        ns = self._parse(["extract", "/path", "-o", "/out"])
        assert ns.output == "/out"

    def test_output_long_flag(self) -> None:
        ns = self._parse(["extract", "/path", "--output", "/out"])
        assert ns.output == "/out"

    def test_format_flag(self) -> None:
        ns = self._parse(["extract", "/path", "--format", "csv"])
        assert ns.format == "csv"

    def test_format_short_flag(self) -> None:
        ns = self._parse(["extract", "/path", "-f", "csv"])
        assert ns.format == "csv"

    def test_no_recursive(self) -> None:
        ns = self._parse(["extract", "/path", "--no-recursive"])
        assert ns.recursive is False

    def test_recursive_explicit(self) -> None:
        ns = self._parse(["extract", "/path", "--recursive"])
        assert ns.recursive is True

    def test_types_flag(self) -> None:
        ns = self._parse(["extract", "/path", "--types", "twb,pbix"])
        assert ns.types == "twb,pbix"

    def test_types_short_flag(self) -> None:
        ns = self._parse(["extract", "/path", "-t", "rdl"])
        assert ns.types == "rdl"

    def test_verbose_flag(self) -> None:
        ns = self._parse(["extract", "/path", "--verbose"])
        assert ns.verbose is True

    def test_verbose_short_flag(self) -> None:
        ns = self._parse(["extract", "/path", "-v"])
        assert ns.verbose is True

    def test_quiet_flag(self) -> None:
        ns = self._parse(["extract", "/path", "--quiet"])
        assert ns.quiet is True

    def test_quiet_short_flag(self) -> None:
        ns = self._parse(["extract", "/path", "-q"])
        assert ns.quiet is True

    def test_verbose_and_quiet_are_mutually_exclusive(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["extract", "/path", "--verbose", "--quiet"])

    def test_recursive_and_no_recursive_are_mutually_exclusive(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["extract", "/path", "--recursive", "--no-recursive"])

    def test_sanitize_passwords(self) -> None:
        ns = self._parse(["extract", "/path", "--sanitize", "passwords"])
        assert ns.sanitize == "passwords"

    def test_sanitize_full(self) -> None:
        ns = self._parse(["extract", "/path", "--sanitize", "full"])
        assert ns.sanitize == "full"

    def test_sanitize_none(self) -> None:
        ns = self._parse(["extract", "/path", "--sanitize", "none"])
        assert ns.sanitize == "none"

    def test_sanitize_invalid(self) -> None:
        parser = _build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["extract", "/path", "--sanitize", "invalid"])

    def test_func_is_cmd_extract(self) -> None:
        from bi_extractor.cli.main import cmd_extract
        ns = self._parse(["extract", "/path"])
        assert ns.func is cmd_extract


# ---------------------------------------------------------------------------
# Argument parser — list-formats subcommand
# ---------------------------------------------------------------------------

class TestListFormatsSubcommand:
    def test_func_is_cmd_list_formats(self) -> None:
        from bi_extractor.cli.main import cmd_list_formats
        parser = _build_parser()
        ns = parser.parse_args(["list-formats"])
        assert ns.func is cmd_list_formats

    def test_no_extra_args_needed(self) -> None:
        parser = _build_parser()
        ns = parser.parse_args(["list-formats"])
        assert ns.command == "list-formats"


# ---------------------------------------------------------------------------
# Argument parser — info subcommand
# ---------------------------------------------------------------------------

class TestInfoSubcommand:
    def test_file_path_positional(self) -> None:
        parser = _build_parser()
        ns = parser.parse_args(["info", "/some/file.twb"])
        assert ns.file_path == "/some/file.twb"

    def test_func_is_cmd_info(self) -> None:
        from bi_extractor.cli.main import cmd_info
        parser = _build_parser()
        ns = parser.parse_args(["info", "/some/file.twb"])
        assert ns.func is cmd_info


# ---------------------------------------------------------------------------
# Help output
# ---------------------------------------------------------------------------

class TestHelpOutput:
    def _capture_help(self, args: list[str]) -> str:
        parser = _build_parser()
        buf = StringIO()
        with pytest.raises(SystemExit):
            # argparse writes to stdout; redirect
            old_stdout = sys.stdout
            sys.stdout = buf
            try:
                parser.parse_args(args)
            finally:
                sys.stdout = old_stdout
        return buf.getvalue()

    def test_top_level_help_mentions_commands(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["--help"])
        captured = capsys.readouterr()
        assert "extract" in captured.out
        assert "list-formats" in captured.out
        assert "info" in captured.out

    def test_extract_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["extract", "--help"])
        captured = capsys.readouterr()
        assert "--output" in captured.out
        assert "--format" in captured.out
        assert "--recursive" in captured.out
        assert "--types" in captured.out
        assert "--verbose" in captured.out
        assert "--quiet" in captured.out
        assert "--sanitize" in captured.out

    def test_list_formats_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["list-formats", "--help"])
        captured = capsys.readouterr()
        assert "list-formats" in captured.out or "formats" in captured.out.lower()

    def test_info_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["info", "--help"])
        captured = capsys.readouterr()
        assert "file_path" in captured.out or "file" in captured.out.lower()

    def test_no_command_exits(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            _build_parser().parse_args([])
        assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# cmd_list_formats
# ---------------------------------------------------------------------------

class TestCmdListFormats:
    def test_prints_table_with_parsers(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_parser_info = [
            {
                "tool": "Tableau",
                "name": "TableauParser",
                "extensions": [".twb", ".twbx"],
                "available": True,
                "message": "",
            },
            {
                "tool": "PowerBI",
                "name": "PowerBIParser",
                "extensions": [".pbix"],
                "available": False,
                "message": "Missing: somelib",
            },
        ]
        with patch("bi_extractor.core.registry.get_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.list_parsers.return_value = mock_parser_info
            mock_get_registry.return_value = mock_registry

            from bi_extractor.cli.main import cmd_list_formats
            args = MagicMock()
            result = cmd_list_formats(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "Tableau" in captured.out
        assert "TableauParser" in captured.out
        assert ".twb" in captured.out
        assert "Yes" in captured.out
        assert "PowerBI" in captured.out
        assert "No" in captured.out
        assert "Missing: somelib" in captured.out

    def test_empty_registry_prints_message(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("bi_extractor.core.registry.get_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.list_parsers.return_value = []
            mock_get_registry.return_value = mock_registry

            from bi_extractor.cli.main import cmd_list_formats
            args = MagicMock()
            result = cmd_list_formats(args)

        captured = capsys.readouterr()
        assert result == 0
        assert "No parsers" in captured.out


# ---------------------------------------------------------------------------
# cmd_info
# ---------------------------------------------------------------------------

class TestCmdInfo:
    def test_nonexistent_file_returns_2(self, tmp_path: Path) -> None:
        from bi_extractor.cli.main import cmd_info
        args = MagicMock()
        args.file_path = str(tmp_path / "nonexistent.twb")
        result = cmd_info(args)
        assert result == 2

    def test_directory_returns_2(self, tmp_path: Path) -> None:
        from bi_extractor.cli.main import cmd_info
        args = MagicMock()
        args.file_path = str(tmp_path)  # directory, not file
        result = cmd_info(args)
        assert result == 2

    def test_successful_extraction_returns_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from bi_extractor.core.models import ExtractionResult
        from bi_extractor.cli.main import cmd_info

        fake_file = tmp_path / "report.twb"
        fake_file.write_text("<dummy/>", encoding="utf-8")

        mock_result = ExtractionResult(
            source_file=str(fake_file),
            file_type="twb",
            tool_name="Tableau",
            fields=[MagicMock(), MagicMock()],
            datasources=[MagicMock()],
            parameters=[],
            report_elements=[MagicMock()],
            errors=[],
        )

        with patch("bi_extractor.core.engine.extract_file", return_value=mock_result):
            args = MagicMock()
            args.file_path = str(fake_file)
            result = cmd_info(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "twb" in captured.out
        assert "Tableau" in captured.out
        assert "2" in captured.out   # field count
        assert "1" in captured.out   # datasource count

    def test_extraction_with_errors_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from bi_extractor.core.models import ExtractionResult
        from bi_extractor.cli.main import cmd_info

        fake_file = tmp_path / "report.twb"
        fake_file.write_text("<dummy/>", encoding="utf-8")

        mock_result = ExtractionResult(
            source_file=str(fake_file),
            file_type="twb",
            tool_name="Tableau",
            errors=["something went wrong"],
        )

        with patch("bi_extractor.core.engine.extract_file", return_value=mock_result):
            args = MagicMock()
            args.file_path = str(fake_file)
            result = cmd_info(args)

        assert result == 1
        captured = capsys.readouterr()
        assert "something went wrong" in captured.out


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_list_formats(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch("bi_extractor.core.registry.get_registry") as mock_get_registry:
            mock_registry = MagicMock()
            mock_registry.list_parsers.return_value = [
                {
                    "tool": "Tableau",
                    "name": "TableauParser",
                    "extensions": [".twb"],
                    "available": True,
                    "message": "",
                }
            ]
            mock_get_registry.return_value = mock_registry
            rc = main(["list-formats"])

        assert rc == 0
        captured = capsys.readouterr()
        assert "Tableau" in captured.out

    def test_main_no_args_exits_nonzero(self) -> None:
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code != 0

    def test_main_info_missing_file(self, tmp_path: Path) -> None:
        rc = main(["info", str(tmp_path / "missing.twb")])
        assert rc == 2

    def test_main_extract_missing_path(self, tmp_path: Path) -> None:
        rc = main(["extract", str(tmp_path / "missing_dir")])
        assert rc == 2

    def test_main_extract_empty_dir(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["extract", str(tmp_path)])
        assert rc == 0
        captured = capsys.readouterr()
        assert "No supported files found" in captured.out

    def test_main_extract_quiet_suppresses_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = main(["extract", str(tmp_path), "--quiet"])
        assert rc == 0
        captured = capsys.readouterr()
        # quiet mode: stdout should be empty for "no files" case
        assert captured.out == ""

    def test_main_extract_produces_csv(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from bi_extractor.core.models import ExtractionResult

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        fake_file = input_dir / "report.twb"
        fake_file.write_text("<dummy/>", encoding="utf-8")

        mock_result = ExtractionResult(
            source_file=str(fake_file),
            file_type="twb",
            tool_name="Tableau",
            fields=[],
            errors=[],
        )

        with (
            patch("bi_extractor.core.engine.discover_files", return_value=[fake_file]),
            patch("bi_extractor.core.engine.extract_file", return_value=mock_result),
        ):
            rc = main([
                "extract", str(input_dir),
                "--output", str(output_dir),
                "--no-recursive",
            ])

        assert rc == 0
        captured = capsys.readouterr()
        assert "Extracted metadata" in captured.out
        assert "Output:" in captured.out

    def test_main_extract_partial_failure_returns_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from bi_extractor.core.models import ExtractionResult

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        fake_file1 = input_dir / "good.twb"
        fake_file2 = input_dir / "bad.twb"

        good_result = ExtractionResult(
            source_file=str(fake_file1),
            file_type="twb",
            tool_name="Tableau",
            errors=[],
        )
        bad_result = ExtractionResult(
            source_file=str(fake_file2),
            file_type="twb",
            tool_name="Tableau",
            errors=["parse error"],
        )

        with (
            patch("bi_extractor.core.engine.discover_files", return_value=[fake_file1, fake_file2]),
            patch("bi_extractor.core.engine.extract_file", side_effect=[good_result, bad_result]),
        ):
            rc = main([
                "extract", str(input_dir),
                "--output", str(output_dir),
            ])

        assert rc == 1

    def test_main_extract_total_failure_returns_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from bi_extractor.core.models import ExtractionResult

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        fake_file = input_dir / "bad.twb"
        bad_result = ExtractionResult(
            source_file=str(fake_file),
            file_type="twb",
            tool_name="Tableau",
            errors=["total failure"],
        )

        with (
            patch("bi_extractor.core.engine.discover_files", return_value=[fake_file]),
            patch("bi_extractor.core.engine.extract_file", return_value=bad_result),
        ):
            rc = main([
                "extract", str(input_dir),
                "--output", str(output_dir),
            ])

        assert rc == 2
