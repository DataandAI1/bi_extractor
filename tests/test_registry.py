"""Tests for the parser registry."""

from pathlib import Path

import pytest

from bi_extractor.core.errors import DuplicateExtensionError
from bi_extractor.core.models import ExtractionResult
from bi_extractor.core.registry import ParserRegistry, reset_registry
from bi_extractor.parsers.base import BaseParser


class _DummyParser(BaseParser):
    extensions = [".dummy"]
    tool = "DummyTool"

    def parse(self, file_path: Path) -> ExtractionResult:
        return ExtractionResult(str(file_path), "dummy", self.tool)


class _AnotherParser(BaseParser):
    extensions = [".other", ".oth"]
    tool = "OtherTool"

    def parse(self, file_path: Path) -> ExtractionResult:
        return ExtractionResult(str(file_path), "other", self.tool)


class _ConflictParser(BaseParser):
    extensions = [".dummy"]  # conflicts with _DummyParser
    tool = "ConflictTool"

    def parse(self, file_path: Path) -> ExtractionResult:
        return ExtractionResult(str(file_path), "dummy", self.tool)


class TestParserRegistry:
    def setup_method(self) -> None:
        reset_registry()

    def test_register_and_get(self) -> None:
        reg = ParserRegistry()
        reg.register(_DummyParser())
        parser = reg.get_parser(Path("report.dummy"))
        assert parser is not None
        assert parser.tool == "DummyTool"

    def test_get_returns_none_for_unknown(self) -> None:
        reg = ParserRegistry()
        assert reg.get_parser(Path("report.xyz")) is None

    def test_get_parser_or_raise(self) -> None:
        from bi_extractor.core.errors import UnsupportedFormatError

        reg = ParserRegistry()
        with pytest.raises(UnsupportedFormatError):
            reg.get_parser_or_raise(Path("report.xyz"))

    def test_case_insensitive(self) -> None:
        reg = ParserRegistry()
        reg.register(_DummyParser())
        assert reg.get_parser(Path("REPORT.DUMMY")) is not None
        assert reg.get_parser(Path("report.Dummy")) is not None

    def test_duplicate_extension_raises(self) -> None:
        reg = ParserRegistry()
        reg.register(_DummyParser())
        with pytest.raises(DuplicateExtensionError):
            reg.register(_ConflictParser())

    def test_multiple_extensions(self) -> None:
        reg = ParserRegistry()
        reg.register(_AnotherParser())
        assert reg.get_parser(Path("x.other")) is not None
        assert reg.get_parser(Path("x.oth")) is not None

    def test_list_parsers(self) -> None:
        reg = ParserRegistry()
        reg.register(_DummyParser())
        reg.register(_AnotherParser())
        parsers = reg.list_parsers()
        assert len(parsers) == 2
        tools = {p["tool"] for p in parsers}
        assert "DummyTool" in tools
        assert "OtherTool" in tools
        # Check structure
        for p in parsers:
            assert "name" in p
            assert "extensions" in p
            assert "available" in p

    def test_supported_extensions(self) -> None:
        reg = ParserRegistry()
        reg.register(_DummyParser())
        reg.register(_AnotherParser())
        exts = reg.supported_extensions()
        assert ".dummy" in exts
        assert ".other" in exts
        assert ".oth" in exts

    def test_auto_discover(self) -> None:
        """Auto-discovery should not crash even with no parsers registered."""
        reg = ParserRegistry()
        reg.auto_discover()
        # Should have discovered zero parsers if none are implemented yet
        # (or some if parsers exist). Just verify it doesn't crash.
        assert isinstance(reg.supported_extensions(), set)
