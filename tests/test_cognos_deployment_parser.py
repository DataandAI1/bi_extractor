"""Tests for the IBM Cognos deployment archive (.cab) parser."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bi_extractor.parsers.cognos.deployment_parser import CognosDeploymentParser


@pytest.fixture
def parser() -> CognosDeploymentParser:
    return CognosDeploymentParser()


class TestCognosDeploymentParserContract:
    def test_extensions(self, parser: CognosDeploymentParser) -> None:
        assert ".cab" in parser.extensions

    def test_tool_name(self, parser: CognosDeploymentParser) -> None:
        assert parser.tool == "IBM Cognos Analytics"

    def test_can_parse_cab(self, parser: CognosDeploymentParser) -> None:
        assert parser.can_parse(Path("deployment.cab")) is True

    def test_cannot_parse_other_extension(self, parser: CognosDeploymentParser) -> None:
        assert parser.can_parse(Path("report.twb")) is False


class TestCognosDeploymentParserNoDependency:
    """Tests that run regardless of whether cabarchive is installed."""

    def test_missing_file_returns_error_or_dep_msg(
        self, parser: CognosDeploymentParser, tmp_path: Path
    ) -> None:
        result = parser.parse(tmp_path / "nonexistent.cab")
        assert result.errors, "Expected errors for missing file or missing dependency"

    def test_check_dependencies_reports_status(
        self, parser: CognosDeploymentParser,
    ) -> None:
        available, message = parser.check_dependencies()
        # Either cabarchive is installed (True, "") or not (False, "pip install ...")
        if not available:
            assert "cabarchive" in message

    @patch("bi_extractor.parsers.cognos.deployment_parser._HAS_CABARCHIVE", False)
    def test_parse_without_cabarchive_returns_error(
        self, tmp_path: Path,
    ) -> None:
        parser = CognosDeploymentParser()
        cab_file = tmp_path / "test.cab"
        cab_file.write_bytes(b"fake cab content")
        result = parser.parse(cab_file)
        assert any("cabarchive" in e for e in result.errors)

    def test_result_has_correct_tool_name(
        self, parser: CognosDeploymentParser, tmp_path: Path
    ) -> None:
        result = parser.parse(tmp_path / "test.cab")
        assert result.tool_name == "IBM Cognos Analytics"

    def test_result_has_correct_file_type(
        self, parser: CognosDeploymentParser, tmp_path: Path
    ) -> None:
        result = parser.parse(tmp_path / "test.cab")
        assert result.file_type == "cab"


class TestCognosDeploymentParserWithMockedCab:
    """Tests using mocked cabarchive to verify extraction logic."""

    def _make_mock_cab(self, xml_content: str, entry_name: str = "report.xml") -> MagicMock:
        """Create a mock CabArchive with a single XML entry."""
        mock_entry = MagicMock()
        mock_entry.buf = xml_content.encode("utf-8")

        mock_cab = MagicMock()
        mock_cab.keys.return_value = [entry_name]
        mock_cab.__getitem__ = lambda self, key: mock_entry
        return mock_cab

    @patch("bi_extractor.parsers.cognos.deployment_parser._HAS_CABARCHIVE", True)
    @patch("bi_extractor.parsers.cognos.deployment_parser.cabarchive")
    def test_extracts_datasource_from_xml(
        self, mock_cabmod: MagicMock, tmp_path: Path
    ) -> None:
        xml = '<deployment><dataSource name="ProdDB" connectionType="JDBC"/></deployment>'
        mock_cabmod.CabArchive.return_value = self._make_mock_cab(xml)

        cab_file = tmp_path / "deploy.cab"
        cab_file.write_bytes(b"fake")

        parser = CognosDeploymentParser()
        result = parser.parse(cab_file)
        assert len(result.datasources) == 1
        assert result.datasources[0].name == "ProdDB"

    @patch("bi_extractor.parsers.cognos.deployment_parser._HAS_CABARCHIVE", True)
    @patch("bi_extractor.parsers.cognos.deployment_parser.cabarchive")
    def test_extracts_fields_from_xml(
        self, mock_cabmod: MagicMock, tmp_path: Path
    ) -> None:
        xml = """<deployment>
            <queryItem name="Revenue" dataType="decimal" expression="sum(amount)"/>
            <queryItem name="Region" dataType="varchar"/>
        </deployment>"""
        mock_cabmod.CabArchive.return_value = self._make_mock_cab(xml)

        cab_file = tmp_path / "deploy.cab"
        cab_file.write_bytes(b"fake")

        parser = CognosDeploymentParser()
        result = parser.parse(cab_file)
        assert len(result.fields) == 2
        names = {f.name for f in result.fields}
        assert names == {"Revenue", "Region"}

    @patch("bi_extractor.parsers.cognos.deployment_parser._HAS_CABARCHIVE", True)
    @patch("bi_extractor.parsers.cognos.deployment_parser.cabarchive")
    def test_extracts_parameters_from_xml(
        self, mock_cabmod: MagicMock, tmp_path: Path
    ) -> None:
        xml = '<deployment><parameter name="p_year" dataType="integer" defaultValue="2024"/></deployment>'
        mock_cabmod.CabArchive.return_value = self._make_mock_cab(xml)

        cab_file = tmp_path / "deploy.cab"
        cab_file.write_bytes(b"fake")

        parser = CognosDeploymentParser()
        result = parser.parse(cab_file)
        assert len(result.parameters) == 1
        assert result.parameters[0].name == "p_year"

    @patch("bi_extractor.parsers.cognos.deployment_parser._HAS_CABARCHIVE", True)
    @patch("bi_extractor.parsers.cognos.deployment_parser.cabarchive")
    def test_extracts_report_elements_from_xml(
        self, mock_cabmod: MagicMock, tmp_path: Path
    ) -> None:
        xml = '<deployment><report name="MonthlySales"/><query name="Q1"/></deployment>'
        mock_cabmod.CabArchive.return_value = self._make_mock_cab(xml)

        cab_file = tmp_path / "deploy.cab"
        cab_file.write_bytes(b"fake")

        parser = CognosDeploymentParser()
        result = parser.parse(cab_file)
        assert len(result.report_elements) == 2
        names = {e.name for e in result.report_elements}
        assert names == {"MonthlySales", "Q1"}

    @patch("bi_extractor.parsers.cognos.deployment_parser._HAS_CABARCHIVE", True)
    @patch("bi_extractor.parsers.cognos.deployment_parser.cabarchive")
    def test_no_xml_entries_returns_error(
        self, mock_cabmod: MagicMock, tmp_path: Path
    ) -> None:
        mock_cab = MagicMock()
        mock_cab.keys.return_value = ["readme.txt", "data.bin"]
        mock_cabmod.CabArchive.return_value = mock_cab

        cab_file = tmp_path / "deploy.cab"
        cab_file.write_bytes(b"fake")

        parser = CognosDeploymentParser()
        result = parser.parse(cab_file)
        assert any("No XML files found" in e for e in result.errors)

    @patch("bi_extractor.parsers.cognos.deployment_parser._HAS_CABARCHIVE", True)
    @patch("bi_extractor.parsers.cognos.deployment_parser.cabarchive")
    def test_metadata_tracks_archive_entries(
        self, mock_cabmod: MagicMock, tmp_path: Path
    ) -> None:
        xml = "<deployment/>"
        mock_cab = MagicMock()
        mock_cab.keys.return_value = ["report.xml", "connections.xml", "readme.txt"]
        mock_entry = MagicMock()
        mock_entry.buf = xml.encode("utf-8")
        mock_cab.__getitem__ = lambda self, key: mock_entry
        mock_cabmod.CabArchive.return_value = mock_cab

        cab_file = tmp_path / "deploy.cab"
        cab_file.write_bytes(b"fake")

        parser = CognosDeploymentParser()
        result = parser.parse(cab_file)
        assert "archive_entries" in result.metadata
        assert "xml_entries" in result.metadata
        assert result.metadata["xml_entries"] == ["report.xml", "connections.xml"]
