"""Tests for the abstract base parser."""

from pathlib import Path

import pytest

from bi_extractor.core.models import ExtractionResult
from bi_extractor.parsers.base import BaseParser


class TestBaseParserContract:
    def test_cannot_instantiate_directly(self) -> None:
        with pytest.raises(TypeError):
            BaseParser()  # type: ignore[abstract]

    def test_subclass_must_define_extensions(self) -> None:
        with pytest.raises(TypeError, match="must define 'extensions'"):

            class BadParser(BaseParser):
                tool = "Test"

                def parse(self, file_path: Path) -> ExtractionResult:
                    return ExtractionResult("", "", "")

            BadParser()

    def test_subclass_must_define_tool(self) -> None:
        with pytest.raises(TypeError, match="must define 'tool'"):

            class BadParser(BaseParser):
                extensions = [".test"]

                def parse(self, file_path: Path) -> ExtractionResult:
                    return ExtractionResult("", "", "")

            BadParser()

    def test_valid_subclass(self) -> None:
        class GoodParser(BaseParser):
            extensions = [".good", ".gd"]
            tool = "GoodTool"

            def parse(self, file_path: Path) -> ExtractionResult:
                return ExtractionResult(
                    source_file=str(file_path),
                    file_type="good",
                    tool_name=self.tool,
                )

        parser = GoodParser()
        assert parser.extensions == [".good", ".gd"]
        assert parser.tool == "GoodTool"

    def test_can_parse_matching_extension(self) -> None:
        class TestParser(BaseParser):
            extensions = [".twb", ".twbx"]
            tool = "Tableau"

            def parse(self, file_path: Path) -> ExtractionResult:
                return ExtractionResult(str(file_path), "twb", "Tableau")

        parser = TestParser()
        assert parser.can_parse(Path("report.twb")) is True
        assert parser.can_parse(Path("report.TWB")) is True
        assert parser.can_parse(Path("report.twbx")) is True
        assert parser.can_parse(Path("report.pbix")) is False

    def test_check_dependencies_default(self) -> None:
        class TestParser(BaseParser):
            extensions = [".test"]
            tool = "Test"

            def parse(self, file_path: Path) -> ExtractionResult:
                return ExtractionResult(str(file_path), "test", "Test")

        parser = TestParser()
        available, message = parser.check_dependencies()
        assert available is True

    def test_check_dependencies_override(self) -> None:
        class TestParser(BaseParser):
            extensions = [".test"]
            tool = "Test"

            def parse(self, file_path: Path) -> ExtractionResult:
                return ExtractionResult(str(file_path), "test", "Test")

            def check_dependencies(self) -> tuple[bool, str]:
                return False, "Install test-lib: pip install test-lib"

        parser = TestParser()
        available, message = parser.check_dependencies()
        assert available is False
        assert "pip install" in message
