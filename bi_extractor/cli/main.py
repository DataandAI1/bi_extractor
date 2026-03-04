"""CLI entry point for bi-extractor.

Provides three subcommands:
  extract      -- discover and extract metadata from BI report files
  list-formats -- show all supported formats and their dependency status
  info         -- show a quick summary for a single file
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _configure_logging(verbose: bool, quiet: bool) -> None:
    """Set root logger level based on --verbose / --quiet flags."""
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.WARNING

    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        level=level,
        stream=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Table rendering (no third-party deps required)
# ---------------------------------------------------------------------------

def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a plain-text table with column padding."""
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(cell))

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"

    lines = [sep, header_line, sep]
    for row in rows:
        cells = [
            (row[i] if i < len(row) else "").ljust(col_widths[i])
            for i in range(len(headers))
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append(sep)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Subcommand: list-formats
# ---------------------------------------------------------------------------

def cmd_list_formats(_args: argparse.Namespace) -> int:
    """Print a table of all registered parsers and their dependency status."""
    from bi_extractor.core.registry import get_registry

    registry = get_registry()
    parsers = registry.list_parsers()

    if not parsers:
        print("No parsers registered.")
        return 0

    headers = ["Tool", "Parser", "Extensions", "Available", "Notes"]
    rows: list[list[str]] = []
    for p in parsers:
        exts = ", ".join(str(e) for e in p["extensions"])  # type: ignore[arg-type]
        available = "Yes" if p["available"] else "No"
        notes = str(p["message"]) if p["message"] else ""
        rows.append([str(p["tool"]), str(p["name"]), exts, available, notes])

    print(_render_table(headers, rows))
    return 0


# ---------------------------------------------------------------------------
# Subcommand: info
# ---------------------------------------------------------------------------

def cmd_info(args: argparse.Namespace) -> int:
    """Print a quick summary for a single file."""
    from bi_extractor.core.engine import extract_file

    file_path = Path(args.file_path)
    if not file_path.exists():
        print(f"Error: file not found: {file_path}", file=sys.stderr)
        return 2
    if not file_path.is_file():
        print(f"Error: path is not a file: {file_path}", file=sys.stderr)
        return 2

    result = extract_file(file_path)

    print(f"File:        {file_path}")
    print(f"File Type:   {result.file_type}")
    print(f"Tool:        {result.tool_name}")
    print(f"Fields:      {len(result.fields)}")
    print(f"Datasources: {len(result.datasources)}")
    print(f"Parameters:  {len(result.parameters)}")
    print(f"Elements:    {len(result.report_elements)}")

    if result.errors:
        print(f"Errors ({len(result.errors)}):")
        for err in result.errors:
            print(f"  - {err}")
        return 1

    return 0


# ---------------------------------------------------------------------------
# Subcommand: extract
# ---------------------------------------------------------------------------

def _parse_extensions(types_str: str | None) -> set[str] | None:
    """Convert a comma-separated type string like 'twb,pbix' to a set of extensions."""
    if not types_str:
        return None
    exts: set[str] = set()
    for token in types_str.split(","):
        token = token.strip().lstrip(".")
        if token:
            exts.add(f".{token.lower()}")
    return exts if exts else None


def cmd_extract(args: argparse.Namespace) -> int:
    """Discover and extract metadata from BI report files."""
    from bi_extractor.core.engine import discover_files, extract_file
    from bi_extractor.core.registry import get_registry
    from bi_extractor.output.csv_formatter import CsvFormatter

    input_path = Path(args.input_path)
    if not input_path.exists():
        print(f"Error: path does not exist: {input_path}", file=sys.stderr)
        return 2

    output_dir = Path(args.output) if args.output else Path.cwd()
    output_dir.mkdir(parents=True, exist_ok=True)

    extensions = _parse_extensions(getattr(args, "types", None))
    recursive: bool = args.recursive

    # Discover files
    files = discover_files(input_path, recursive=recursive, extensions=extensions)

    if not files:
        if not args.quiet:
            print("No supported files found.")
        return 0

    total = len(files)
    if not args.quiet:
        print(f"Found {total} file(s) to process.")

    # Extract
    registry = get_registry()
    results = []
    error_count = 0

    for idx, file_path in enumerate(files, start=1):
        if not args.quiet:
            print(f"Processing file {idx} of {total}: {file_path.name}")

        result = extract_file(file_path, registry)
        results.append(result)

        if result.errors:
            error_count += 1
            if args.verbose:
                for err in result.errors:
                    print(f"  Warning: {err}", file=sys.stderr)

    # Write output
    if args.format == "csv":
        formatter = CsvFormatter()
        output_file = formatter.write(results, output_dir)
    else:
        print(f"Error: unsupported format '{args.format}'", file=sys.stderr)
        return 2

    success_count = total - error_count

    if not args.quiet:
        print(
            f"Extracted metadata from {success_count} file(s) "
            f"({error_count} error(s)). Output: {output_file}"
        )

    if error_count == total:
        return 2  # total failure
    if error_count > 0:
        return 1  # partial failure
    return 0  # success


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bi-extractor",
        description="Universal BI Report Metadata Extractor",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # -- extract --
    extract_p = subparsers.add_parser(
        "extract",
        help="Extract metadata from BI report files",
        description="Discover and extract metadata from BI report files in a directory or single file.",
    )
    extract_p.add_argument(
        "input_path",
        metavar="<input_path>",
        help="File or directory to scan for BI report files",
    )
    extract_p.add_argument(
        "--output", "-o",
        default=None,
        metavar="DIR",
        help="Output directory (default: current directory)",
    )
    extract_p.add_argument(
        "--format", "-f",
        default="csv",
        choices=["csv"],
        metavar="FORMAT",
        help="Output format: csv (default: csv)",
    )

    recursive_group = extract_p.add_mutually_exclusive_group()
    recursive_group.add_argument(
        "--recursive",
        dest="recursive",
        action="store_true",
        default=True,
        help="Scan directories recursively (default)",
    )
    recursive_group.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Do not scan subdirectories",
    )

    extract_p.add_argument(
        "--types", "-t",
        default=None,
        metavar="TYPES",
        help="Comma-separated file type extensions to include (e.g. twb,pbix,rdl)",
    )

    verbosity_group = extract_p.add_mutually_exclusive_group()
    verbosity_group.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Verbose output",
    )
    verbosity_group.add_argument(
        "--quiet", "-q",
        action="store_true",
        default=False,
        help="Suppress all output except errors",
    )

    extract_p.add_argument(
        "--sanitize",
        default="passwords",
        choices=["passwords", "full", "none"],
        help="Sanitization level: passwords (default), full, none",
    )

    extract_p.set_defaults(func=cmd_extract)

    # -- list-formats --
    list_p = subparsers.add_parser(
        "list-formats",
        help="Show all supported formats with dependency status",
        description="Display a table of all registered parsers and whether their dependencies are available.",
    )
    list_p.set_defaults(func=cmd_list_formats)

    # -- info --
    info_p = subparsers.add_parser(
        "info",
        help="Show a quick summary for a single file",
        description="Extract and display a quick metadata summary for a single BI report file.",
    )
    info_p.add_argument(
        "file_path",
        metavar="<file_path>",
        help="Path to the BI report file",
    )
    info_p.set_defaults(func=cmd_info)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    """Main entry point registered as the 'bi-extractor' console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Configure logging for subcommands that have verbose/quiet flags
    verbose = getattr(args, "verbose", False)
    quiet = getattr(args, "quiet", False)
    _configure_logging(verbose=verbose, quiet=quiet)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
