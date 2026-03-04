"""Tests for the JasperReports JRXML parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from bi_extractor.core.models import ExtractionResult
from bi_extractor.parsers.jasper.jrxml_parser import JrxmlParser

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "jasper"
SAMPLE = FIXTURES_DIR / "sample.jrxml"


@pytest.fixture
def parser() -> JrxmlParser:
    return JrxmlParser()


@pytest.fixture
def result(parser: JrxmlParser) -> ExtractionResult:
    return parser.parse(SAMPLE)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestJrxmlParserContract:
    def test_extensions(self, parser: JrxmlParser) -> None:
        assert ".jrxml" in parser.extensions

    def test_tool(self, parser: JrxmlParser) -> None:
        assert parser.tool == "JasperReports"

    def test_can_parse_jrxml(self, parser: JrxmlParser) -> None:
        assert parser.can_parse(Path("report.jrxml")) is True
        assert parser.can_parse(Path("report.JRXML")) is True

    def test_cannot_parse_other(self, parser: JrxmlParser) -> None:
        assert parser.can_parse(Path("report.pbix")) is False
        assert parser.can_parse(Path("report.twb")) is False

    def test_check_dependencies(self, parser: JrxmlParser) -> None:
        available, _ = parser.check_dependencies()
        assert available is True


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


class TestResultShape:
    def test_returns_extraction_result(self, result: ExtractionResult) -> None:
        assert isinstance(result, ExtractionResult)

    def test_no_errors(self, result: ExtractionResult) -> None:
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_source_file(self, result: ExtractionResult) -> None:
        assert result.source_file == str(SAMPLE)

    def test_file_type(self, result: ExtractionResult) -> None:
        assert result.file_type == ".jrxml"

    def test_tool_name(self, result: ExtractionResult) -> None:
        assert result.tool_name == "JasperReports"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_report_name_extracted(self, result: ExtractionResult) -> None:
        assert result.metadata.get("name") == "SalesReport"

    def test_page_dimensions_extracted(self, result: ExtractionResult) -> None:
        assert result.metadata.get("pageWidth") == "595"
        assert result.metadata.get("pageHeight") == "842"

    def test_query_extracted(self, result: ExtractionResult) -> None:
        query = result.metadata.get("query", "")
        assert "SELECT" in query
        assert "orders" in query

    def test_query_contains_expected_columns(self, result: ExtractionResult) -> None:
        query = result.metadata.get("query", "")
        for col in ("order_id", "customer_name", "order_date", "amount", "region"):
            assert col in query, f"Expected column '{col}' in query"


# ---------------------------------------------------------------------------
# Datasource
# ---------------------------------------------------------------------------


class TestDatasource:
    def test_datasource_extracted(self, result: ExtractionResult) -> None:
        assert len(result.datasources) >= 1

    def test_datasource_name(self, result: ExtractionResult) -> None:
        ds = result.datasources[0]
        assert ds.name == "SalesReport"

    def test_datasource_type_jdbc(self, result: ExtractionResult) -> None:
        ds = result.datasources[0]
        assert ds.connection_type == "jdbc"


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------


class TestFields:
    def _regular_fields(self, result: ExtractionResult) -> list:
        return [f for f in result.fields if f.field_type == "regular"]

    def test_five_regular_fields(self, result: ExtractionResult) -> None:
        assert len(self._regular_fields(result)) == 5

    def test_field_names(self, result: ExtractionResult) -> None:
        names = {f.name for f in self._regular_fields(result)}
        assert names == {"order_id", "customer_name", "order_date", "amount", "region"}

    def test_integer_field_type(self, result: ExtractionResult) -> None:
        order_id = next(f for f in self._regular_fields(result) if f.name == "order_id")
        assert order_id.data_type == "integer"

    def test_string_field_type(self, result: ExtractionResult) -> None:
        customer = next(f for f in self._regular_fields(result) if f.name == "customer_name")
        assert customer.data_type == "string"

    def test_date_field_type(self, result: ExtractionResult) -> None:
        order_date = next(f for f in self._regular_fields(result) if f.name == "order_date")
        assert order_date.data_type == "date"

    def test_bigdecimal_maps_to_float(self, result: ExtractionResult) -> None:
        amount = next(f for f in self._regular_fields(result) if f.name == "amount")
        assert amount.data_type == "float"

    def test_field_type_is_regular(self, result: ExtractionResult) -> None:
        for f in self._regular_fields(result):
            assert f.field_type == "regular"


# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------


class TestVariables:
    def _calculated(self, result: ExtractionResult) -> list:
        return [f for f in result.fields if f.field_type == "calculated"]

    def test_two_variables(self, result: ExtractionResult) -> None:
        assert len(self._calculated(result)) == 2

    def test_variable_names(self, result: ExtractionResult) -> None:
        names = {f.name for f in self._calculated(result)}
        assert names == {"totalAmount", "orderCount"}

    def test_total_amount_has_formula(self, result: ExtractionResult) -> None:
        total = next(f for f in self._calculated(result) if f.name == "totalAmount")
        assert "$F{amount}" in total.formula

    def test_order_count_type(self, result: ExtractionResult) -> None:
        count = next(f for f in self._calculated(result) if f.name == "orderCount")
        assert count.data_type == "integer"

    def test_field_type_is_calculated(self, result: ExtractionResult) -> None:
        for v in self._calculated(result):
            assert v.field_type == "calculated"


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


class TestParameters:
    def test_two_user_parameters(self, result: ExtractionResult) -> None:
        # REPORT_CONNECTION should be filtered out
        assert len(result.parameters) == 2

    def test_parameter_names(self, result: ExtractionResult) -> None:
        names = {p.name for p in result.parameters}
        assert names == {"startDate", "region"}

    def test_system_parameter_excluded(self, result: ExtractionResult) -> None:
        names = {p.name for p in result.parameters}
        assert "REPORT_CONNECTION" not in names

    def test_start_date_type(self, result: ExtractionResult) -> None:
        p = next(p for p in result.parameters if p.name == "startDate")
        assert p.data_type == "date"

    def test_region_type(self, result: ExtractionResult) -> None:
        p = next(p for p in result.parameters if p.name == "region")
        assert p.data_type == "string"

    def test_region_default_value(self, result: ExtractionResult) -> None:
        p = next(p for p in result.parameters if p.name == "region")
        assert '"NORTH"' in p.default_value


# ---------------------------------------------------------------------------
# Report elements / bands
# ---------------------------------------------------------------------------


class TestReportElements:
    def _sections(self, result: ExtractionResult) -> list:
        return [e for e in result.report_elements if e.element_type == "section"]

    def _groups(self, result: ExtractionResult) -> list:
        return [e for e in result.report_elements if e.element_type == "group"]

    def test_sections_extracted(self, result: ExtractionResult) -> None:
        section_names = {e.name for e in self._sections(result)}
        for band in ("title", "pageHeader", "columnHeader", "detail", "pageFooter", "summary"):
            assert band in section_names, f"Expected band '{band}' in sections"

    def test_group_extracted(self, result: ExtractionResult) -> None:
        assert len(self._groups(result)) == 1
        assert self._groups(result)[0].name == "regionGroup"

    def test_section_element_type(self, result: ExtractionResult) -> None:
        for e in self._sections(result):
            assert e.element_type == "section"


# ---------------------------------------------------------------------------
# Field usage tracking
# ---------------------------------------------------------------------------


class TestFieldUsage:
    def test_fields_used_populated(self, result: ExtractionResult) -> None:
        sections = [e for e in result.report_elements if e.element_type == "section"]
        # At least one section should have fields_used populated
        used = set()
        for s in sections:
            used.update(s.fields_used)
        assert len(used) > 0, "Expected some field references to be tracked"

    def test_tracked_fields_are_known_names(self, result: ExtractionResult) -> None:
        field_names = {f.name for f in result.fields if f.field_type == "regular"}
        sections = [e for e in result.report_elements if e.element_type == "section"]
        tracked = set()
        for s in sections:
            tracked.update(s.fields_used)
        # All tracked names should be actual field names defined in the report
        for name in tracked:
            assert name in field_names, f"Tracked field '{name}' not in declared fields"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_nonexistent_file_returns_error_result(self, parser: JrxmlParser) -> None:
        result = parser.parse(Path("/nonexistent/path/report.jrxml"))
        assert len(result.errors) > 0
        assert result.tool_name == "JasperReports"

    def test_invalid_xml_returns_error_result(self, parser: JrxmlParser, tmp_path: Path) -> None:
        bad_file = tmp_path / "broken.jrxml"
        bad_file.write_text("<<< not valid xml >>>", encoding="utf-8")
        result = parser.parse(bad_file)
        assert len(result.errors) > 0

    def test_empty_jrxml_does_not_raise(self, parser: JrxmlParser, tmp_path: Path) -> None:
        minimal = tmp_path / "minimal.jrxml"
        minimal.write_text(
            '<?xml version="1.0"?>'
            '<jasperReport xmlns="http://jasperreports.sourceforge.net/jasperreports"'
            ' name="Empty" pageWidth="595" pageHeight="842" columnWidth="535"/>',
            encoding="utf-8",
        )
        result = parser.parse(minimal)
        # Should succeed with no fields/params/elements
        assert result.errors == []
        assert result.fields == []
        assert result.parameters == []
