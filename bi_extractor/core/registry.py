"""Parser registry with auto-discovery.

Discovers and manages parser instances. Maps file extensions to parsers.
Auto-discovery scans the parsers/ package, catching ImportError per-module
so one missing optional dependency never crashes the entire scan.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import TYPE_CHECKING

from bi_extractor.core.errors import DuplicateExtensionError, UnsupportedFormatError

if TYPE_CHECKING:
    from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class ParserRegistry:
    """Discovers and manages parser instances. Maps file extensions to parsers."""

    def __init__(self) -> None:
        self._parsers: dict[str, BaseParser] = {}  # extension -> parser instance
        self._parser_instances: list[BaseParser] = []  # unique parser instances

    def register(self, parser: BaseParser) -> None:
        """Register a parser for its declared extensions.

        Raises DuplicateExtensionError if an extension is already registered.
        """
        parser_name = f"{parser.tool} ({type(parser).__name__})"
        for ext in parser.extensions:
            ext_lower = ext.lower()
            if ext_lower in self._parsers:
                existing = self._parsers[ext_lower]
                existing_name = f"{existing.tool} ({type(existing).__name__})"
                raise DuplicateExtensionError(ext_lower, existing_name, parser_name)
            self._parsers[ext_lower] = parser
        self._parser_instances.append(parser)
        logger.debug("Registered parser: %s for %s", parser_name, parser.extensions)

    def get_parser(self, file_path: Path) -> BaseParser | None:
        """Get the parser for a given file path, or None if unsupported."""
        ext = file_path.suffix.lower()
        return self._parsers.get(ext)

    def get_parser_or_raise(self, file_path: Path) -> BaseParser:
        """Get the parser for a given file path, or raise UnsupportedFormatError."""
        parser = self.get_parser(file_path)
        if parser is None:
            raise UnsupportedFormatError(file_path.suffix)
        return parser

    def list_parsers(self) -> list[dict[str, object]]:
        """List all registered parsers with their metadata and dependency status.

        Returns a list of dicts with: name, tool, extensions, available, message.
        """
        result: list[dict[str, object]] = []
        for parser in self._parser_instances:
            available, message = parser.check_dependencies()
            result.append(
                {
                    "name": type(parser).__name__,
                    "tool": parser.tool,
                    "extensions": parser.extensions,
                    "available": available,
                    "message": message,
                }
            )
        return result

    def supported_extensions(self) -> set[str]:
        """Return all registered file extensions."""
        return set(self._parsers.keys())

    def auto_discover(self) -> None:
        """Scan the parsers/ package for BaseParser subclasses.

        Each parser module is imported inside a try/except so that missing
        optional dependencies produce a warning, never a crash.
        """
        from bi_extractor.parsers import base as _  # noqa: F811

        import bi_extractor.parsers as parsers_pkg

        parsers_path = parsers_pkg.__path__
        # Walk all subpackages (tableau/, microsoft/, etc.)
        for importer, modname, ispkg in pkgutil.walk_packages(
            parsers_path, prefix="bi_extractor.parsers."
        ):
            if modname.endswith("base") or modname.endswith("__init__"):
                continue
            try:
                module = importlib.import_module(modname)
            except ImportError as e:
                logger.warning(
                    "Could not import parser module %s: %s (missing dependency?)",
                    modname,
                    e,
                )
                continue
            except Exception as e:
                logger.warning(
                    "Error importing parser module %s: %s", modname, e
                )
                continue

            # Find BaseParser subclasses in the module
            from bi_extractor.parsers.base import BaseParser

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, BaseParser)
                    and attr is not BaseParser
                    and not getattr(attr, "__abstractmethods__", None)
                ):
                    try:
                        instance = attr()
                        self.register(instance)
                    except DuplicateExtensionError:
                        # Already registered (e.g., imported from another module)
                        pass
                    except Exception as e:
                        logger.warning(
                            "Could not instantiate parser %s.%s: %s",
                            modname,
                            attr_name,
                            e,
                        )


# Global registry singleton
_registry: ParserRegistry | None = None


def get_registry() -> ParserRegistry:
    """Get or create the global parser registry with auto-discovery."""
    global _registry
    if _registry is None:
        _registry = ParserRegistry()
        _registry.auto_discover()
    return _registry


def reset_registry() -> None:
    """Reset the global registry (primarily for testing)."""
    global _registry
    _registry = None
