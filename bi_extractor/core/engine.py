"""Extraction engine — orchestrates file discovery, parsing, and result collection.

The engine accepts a list of file paths (not directories), routes each to
the appropriate parser via the registry, and collects results. Directory
scanning is the responsibility of the CLI/GUI layer.
"""

from __future__ import annotations

import logging
from pathlib import Path

from bi_extractor.core.models import ExtractionResult
from bi_extractor.core.registry import ParserRegistry, get_registry

logger = logging.getLogger(__name__)


def discover_files(
    input_path: Path,
    recursive: bool = True,
    extensions: set[str] | None = None,
) -> list[Path]:
    """Discover supported report files in a directory.

    Args:
        input_path: File or directory to scan.
        recursive: If True, scan subdirectories recursively.
        extensions: If provided, only include these extensions.
                    If None, include all extensions the registry supports.

    Returns:
        Sorted list of file paths.
    """
    if input_path.is_file():
        return [input_path]

    registry = get_registry()
    supported = extensions or registry.supported_extensions()

    files: list[Path] = []
    pattern = "**/*" if recursive else "*"
    for path in input_path.glob(pattern):
        if path.is_file() and path.suffix.lower() in supported:
            files.append(path)

    files.sort()
    return files


def extract_file(
    file_path: Path,
    registry: ParserRegistry | None = None,
) -> ExtractionResult:
    """Extract metadata from a single file.

    Never raises — returns ExtractionResult with errors on failure.
    """
    if registry is None:
        registry = get_registry()

    parser = registry.get_parser(file_path)
    if parser is None:
        return ExtractionResult.error_result(
            source_file=str(file_path),
            file_type=file_path.suffix.lstrip("."),
            tool_name="Unknown",
            error=f"No parser registered for extension: {file_path.suffix}",
        )

    available, msg = parser.check_dependencies()
    if not available:
        return ExtractionResult.error_result(
            source_file=str(file_path),
            file_type=file_path.suffix.lstrip("."),
            tool_name=parser.tool,
            error=f"Missing dependency: {msg}",
        )

    try:
        logger.info("Parsing %s with %s parser", file_path.name, parser.tool)
        result = parser.parse(file_path)
        if result.errors:
            for err in result.errors:
                logger.warning("  Warning in %s: %s", file_path.name, err)
        else:
            logger.info(
                "  Extracted %d fields, %d datasources from %s",
                len(result.fields),
                len(result.datasources),
                file_path.name,
            )
        return result
    except Exception as e:
        logger.error("Error parsing %s: %s", file_path.name, e)
        return ExtractionResult.error_result(
            source_file=str(file_path),
            file_type=file_path.suffix.lstrip("."),
            tool_name=parser.tool,
            error=str(e),
        )


def extract_all(
    file_paths: list[Path],
    registry: ParserRegistry | None = None,
) -> list[ExtractionResult]:
    """Extract metadata from multiple files.

    Processes files sequentially. Never raises — all errors are captured
    in individual ExtractionResult.errors lists.
    """
    if registry is None:
        registry = get_registry()

    results: list[ExtractionResult] = []
    for file_path in file_paths:
        result = extract_file(file_path, registry)
        results.append(result)
    return results
