"""Abstract base parser that all format-specific parsers must implement."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from bi_extractor.core.models import ExtractionResult


class BaseParser(ABC):
    """Contract that all format-specific parsers must implement.

    Subclasses MUST define:
        extensions: ClassVar[list[str]]  — file extensions (e.g., ['.twb', '.twbx'])
        tool: ClassVar[str]              — BI tool name (e.g., 'Tableau')

    Subclasses MUST implement:
        parse(file_path) -> ExtractionResult

    Optional overrides:
        can_parse(file_path) -> bool
        check_dependencies() -> tuple[bool, str]
    """

    extensions: ClassVar[list[str]]
    tool: ClassVar[str]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Validate that subclasses define required class attributes."""
        super().__init_subclass__(**kwargs)
        # Skip validation for intermediate abstract classes
        if getattr(cls, "__abstractmethods__", None):
            return
        if not getattr(cls, "extensions", None):
            raise TypeError(f"{cls.__name__} must define 'extensions' class attribute")
        if not getattr(cls, "tool", None):
            raise TypeError(f"{cls.__name__} must define 'tool' class attribute")

    @abstractmethod
    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a single file and return normalized metadata.

        Must never raise — return ExtractionResult with errors list populated
        on failure.
        """

    def can_parse(self, file_path: Path) -> bool:
        """Check if this parser can handle the given file. Default: check extension."""
        return file_path.suffix.lower() in self.extensions

    def check_dependencies(self) -> tuple[bool, str]:
        """Check if required dependencies are available.

        Returns:
            (available, message) — True if ready, False with install hint if not.
        """
        return True, "No special dependencies required"
