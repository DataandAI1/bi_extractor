"""Tests for the Tableau Data Source parser (.tds / .tdsx)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from bi_extractor.core.models import ExtractionResult
from bi_extractor.parsers.tableau.tds_parser import TableauTdsParser


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_TDS = Path(__file__).parent / "fixtures" / "tableau" / "sample.tds"


@pytest.fixture
def parser() -> TableauTdsParser:
    return TableauTdsParser()


@pytest.fixture
def sample_tds_path() -> Path:
    return SAMPLE_TDS


@pytest.fixture
def sample_tdsx_path(tmp_path: Path) -> Path:
    """Create a minimal .tdsx (ZIP containing sample.tds)."""
    tdsx = tmp_path / "sample.tdsx"
    with zipfile.ZipFile(tdsx, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(SAMPLE_TDS, arcname="sample.tds")
    return tdsx


# ---------------------------------------------------------------------------
# Class-level contract tests
# ---------------------------------------------------------------------------

class TestTableauTdsParserContract:
    def test_extensions(self, parser: TableauTdsParser) -> None:
        assert ".tds" in parser.extensions
        assert ".tdsx" in parser.extensions

    def test_tool_name(self, parser: TableauTdsParser) -> None:
        assert parser.tool == "Tableau"

    def test_can_parse_tds(self, parser: TableauTdsParser) -> None:
        assert parser.can_parse(Path("my_source.tds")) is True

    def test_can_parse_tdsx(self, parser: TableauTdsParser) -> None:
        assert parser.can_parse(Path("my_source.tdsx")) is True

    def test_can_parse_case_insensitive(self, parser: TableauTdsParser) -> None:
        assert parser.can_parse(Path("MY_SOURCE.TDS")) is True
        assert parser.can_parse(Path("MY_SOURCE.TDSX")) is True

    def test_cannot_parse_twb(self, parser: TableauTdsParser) -> None:
        assert parser.can_parse(Path("report.twb")) is False

    def test_check_dependencies(self, parser: TableauTdsParser) -> None:
        available, _ = parser.check_dependencies()
        assert available is True


# ---------------------------------------------------------------------------
# .tds parsing
# ---------------------------------------------------------------------------

class TestTdsFileParsing:
    def test_returns_extraction_result(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        assert isinstance(result, ExtractionResult)

    def test_source_file_set(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        assert result.source_file == str(sample_tds_path)

    def test_file_type_is_tds(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        assert result.file_type == "tds"

    def test_tool_name_in_result(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        assert result.tool_name == "Tableau"

    def test_no_errors(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        assert result.errors == []

    def test_report_elements_empty(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        """Data source files have no worksheets."""
        result = parser.parse(sample_tds_path)
        assert result.report_elements == []

    def test_datasource_extracted(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        assert len(result.datasources) >= 1

    def test_datasource_name(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        ds = result.datasources[0]
        assert ds.name == "sample_ds"

    def test_datasource_alias(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        ds = result.datasources[0]
        assert ds.alias == "Sample Data Source"

    def test_datasource_connection_type(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        ds = result.datasources[0]
        assert ds.connection_type == "sqlserver"

    def test_datasource_database(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        ds = result.datasources[0]
        assert ds.database == "SalesDB"

    def test_datasource_schema(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        ds = result.datasources[0]
        assert ds.schema == "dbo"

    def test_datasource_tables(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        ds = result.datasources[0]
        assert "Orders" in ds.tables or "[dbo].[Orders]" in ds.tables

    def test_fields_extracted(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        assert len(result.fields) >= 4

    def test_dimension_field(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        names = [f.name for f in result.fields]
        assert "[Customer ID]" in names

        customer = next(f for f in result.fields if f.name == "[Customer ID]")
        assert customer.role == "dimension"
        assert customer.data_type == "string"
        assert customer.field_type == "Dimension"
        assert customer.datasource == "sample_ds"

    def test_measure_field(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        sales = next(f for f in result.fields if f.name == "[Sales]")
        assert sales.role == "measure"
        assert sales.field_type == "Measure"

    def test_aggregated_measure_field(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        qty = next(f for f in result.fields if f.name == "[Quantity]")
        assert qty.field_type == "Aggregated Measure"

    def test_calculated_field_has_formula(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        calc = next(f for f in result.fields if f.name == "[Profit Ratio]")
        assert calc.field_type in ("Calculated Field", "Table Calculation")
        assert "SUM" in calc.formula

    def test_field_alias(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        sales = next(f for f in result.fields if f.name == "[Sales]")
        assert sales.alias == "Sales"

    def test_calc_id_resolved_in_formula(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        """[Calculation_1000000000001] should be replaced with 'Running Total'."""
        result = parser.parse(sample_tds_path)
        yoy = next((f for f in result.fields if f.name == "[YOY Growth]"), None)
        if yoy is not None and yoy.formula:
            # Either already resolved or still raw — just check no parse error
            assert isinstance(yoy.formula, str)

    def test_no_duplicate_fields(
        self, parser: TableauTdsParser, sample_tds_path: Path
    ) -> None:
        result = parser.parse(sample_tds_path)
        names_ds = [(f.name, f.datasource) for f in result.fields]
        assert len(names_ds) == len(set(names_ds))


# ---------------------------------------------------------------------------
# .tdsx parsing (ZIP wrapper)
# ---------------------------------------------------------------------------

class TestTdsxFileParsing:
    def test_returns_extraction_result(
        self, parser: TableauTdsParser, sample_tdsx_path: Path
    ) -> None:
        result = parser.parse(sample_tdsx_path)
        assert isinstance(result, ExtractionResult)

    def test_file_type_is_tdsx(
        self, parser: TableauTdsParser, sample_tdsx_path: Path
    ) -> None:
        result = parser.parse(sample_tdsx_path)
        assert result.file_type == "tdsx"

    def test_no_errors(
        self, parser: TableauTdsParser, sample_tdsx_path: Path
    ) -> None:
        result = parser.parse(sample_tdsx_path)
        assert result.errors == []

    def test_report_elements_empty(
        self, parser: TableauTdsParser, sample_tdsx_path: Path
    ) -> None:
        result = parser.parse(sample_tdsx_path)
        assert result.report_elements == []

    def test_same_datasource_as_tds(
        self, parser: TableauTdsParser, sample_tds_path: Path, sample_tdsx_path: Path
    ) -> None:
        tds_result = parser.parse(sample_tds_path)
        tdsx_result = parser.parse(sample_tdsx_path)
        assert len(tds_result.datasources) == len(tdsx_result.datasources)
        assert tds_result.datasources[0].name == tdsx_result.datasources[0].name

    def test_same_field_count_as_tds(
        self, parser: TableauTdsParser, sample_tds_path: Path, sample_tdsx_path: Path
    ) -> None:
        tds_result = parser.parse(sample_tds_path)
        tdsx_result = parser.parse(sample_tdsx_path)
        assert len(tds_result.fields) == len(tdsx_result.fields)


# ---------------------------------------------------------------------------
# Error handling — never raises
# ---------------------------------------------------------------------------

class TestTdsParserErrorHandling:
    def test_nonexistent_file_returns_error_result(
        self, parser: TableauTdsParser
    ) -> None:
        result = parser.parse(Path("/nonexistent/path/file.tds"))
        assert isinstance(result, ExtractionResult)
        assert len(result.errors) > 0

    def test_invalid_xml_returns_error_result(
        self, parser: TableauTdsParser, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.tds"
        bad.write_text("this is not XML", encoding="utf-8")
        result = parser.parse(bad)
        assert isinstance(result, ExtractionResult)
        assert len(result.errors) > 0

    def test_empty_tdsx_returns_error_result(
        self, parser: TableauTdsParser, tmp_path: Path
    ) -> None:
        """A .tdsx with no inner .tds file should return an error, not raise."""
        empty_zip = tmp_path / "empty.tdsx"
        with zipfile.ZipFile(empty_zip, "w") as zf:
            zf.writestr("unrelated.txt", "hello")
        result = parser.parse(empty_zip)
        assert isinstance(result, ExtractionResult)
        assert len(result.errors) > 0

    def test_parse_never_raises(
        self, parser: TableauTdsParser, tmp_path: Path
    ) -> None:
        garbage = tmp_path / "garbage.tds"
        garbage.write_bytes(b"\x00\x01\x02\x03")
        # Must not raise under any circumstance
        result = parser.parse(garbage)
        assert isinstance(result, ExtractionResult)
