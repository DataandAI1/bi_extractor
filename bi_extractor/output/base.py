"""Abstract base for output formatters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from bi_extractor.core.models import ExtractionResult


class BaseFormatter(ABC):
    """Contract for output formatters (CSV, JSON, Excel)."""

    @abstractmethod
    def format_name(self) -> str:
        """Return the format name (e.g., 'csv', 'json', 'excel')."""

    @abstractmethod
    def write(
        self,
        results: list[ExtractionResult],
        output_path: Path,
    ) -> Path:
        """Write extraction results to the output path.

        Args:
            results: List of extraction results from one or more files.
            output_path: Directory to write output into.

        Returns:
            Path to the written output file.
        """
