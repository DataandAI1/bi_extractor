"""Tests for the MicroStrategy .mstr parser."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from bi_extractor.parsers.microstrategy.mstr_parser import MstrParser

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_XML_CONTENT = '''\
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://www.microstrategy.com/schema"
         name="Sales Analytics"
         description="Sales reporting project">
  <dataSources>
    <dataSource name="SalesWarehouse" type="ODBC"
                connectionString="DSN=SalesWH;UID=reader"
                database="sales_dw" schema="dbo">
      <table name="fact_sales"/>
      <table name="dim_customer"/>
      <table name="dim_product"/>
    </dataSource>
  </dataSources>
  <attributes>
    <attribute name="Customer" dataType="varchar"
               table="dim_customer" column="customer_name"
               description="Customer full name"/>
    <attribute name="Region" dataType="varchar"
               table="dim_customer" column="region"/>
    <attribute name="Product" dataType="varchar"
               table="dim_product" column="product_name"/>
  </attributes>
  <metrics>
    <metric name="Revenue" dataType="decimal"
            formula="Sum(fact_sales.amount)"
            description="Total revenue"/>
    <metric name="Order Count" dataType="integer"
            formula="Count(fact_sales.order_id)"/>
  </metrics>
  <reports>
    <report name="Sales Summary" type="grid"
            description="Monthly sales summary">
      <attribute ref="Customer"/>
      <attribute ref="Region"/>
      <metric ref="Revenue"/>
      <metric ref="Order Count"/>
      <filter name="DateRange"
              expression="OrderDate BETWEEN @StartDate AND @EndDate"/>
    </report>
    <report name="Regional Analysis" type="dashboard">
      <attribute ref="Region"/>
      <metric ref="Revenue"/>
    </report>
  </reports>
  <parameters>
    <parameter name="StartDate" dataType="date"
               defaultValue="2024-01-01" prompt="Start Date"/>
    <parameter name="EndDate" dataType="date" prompt="End Date"/>
  </parameters>
</project>'''


def _create_sample_mstr(path: Path) -> Path:
    """Create a synthetic .mstr file (ZIP with XML) for testing."""
    mstr_path = path / "sample.mstr"
    with zipfile.ZipFile(mstr_path, "w") as zf:
        zf.writestr("project.xml", _XML_CONTENT)
    return mstr_path


def _create_plain_xml_mstr(path: Path) -> Path:
    """Create a plain XML .mstr file (no ZIP wrapper)."""
    mstr_path = path / "plain.mstr"
    mstr_path.write_text(_XML_CONTENT, encoding="utf-8")
    return mstr_path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def parser() -> MstrParser:
    return MstrParser()


@pytest.fixture
def sample_mstr(tmp_path: Path) -> Path:
    return _create_sample_mstr(tmp_path)


@pytest.fixture
def plain_xml_mstr(tmp_path: Path) -> Path:
    return _create_plain_xml_mstr(tmp_path)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestMstrParserContract:
    def test_extensions(self, parser: MstrParser) -> None:
        assert ".mstr" in parser.extensions

    def test_tool_name(self, parser: MstrParser) -> None:
        assert parser.tool == "MicroStrategy"

    def test_can_parse_mstr(self, parser: MstrParser) -> None:
        assert parser.can_parse(Path("report.mstr")) is True

    def test_cannot_parse_other_extension(self, parser: MstrParser) -> None:
        assert parser.can_parse(Path("report.rdl")) is False

    def test_check_dependencies(self, parser: MstrParser) -> None:
        available, _ = parser.check_dependencies()
        assert available is True


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestMstrParserErrors:
    def test_missing_file_returns_error(
        self, parser: MstrParser, tmp_path: Path
    ) -> None:
        result = parser.parse(tmp_path / "nonexistent.mstr")
        assert result.errors, "Expected errors for missing file"

    def test_corrupt_zip_returns_error(
        self, parser: MstrParser, tmp_path: Path
    ) -> None:
        bad = tmp_path / "corrupt.mstr"
        bad.write_bytes(b"PK\x03\x04this is not a valid zip or xml")
        result = parser.parse(bad)
        assert result.errors, "Expected errors for corrupt ZIP/XML"

    def test_empty_zip_returns_error(
        self, parser: MstrParser, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty.mstr"
        with zipfile.ZipFile(empty, "w"):
            pass  # create empty ZIP
        result = parser.parse(empty)
        assert result.errors, "Expected errors for ZIP with no XML files"

    def test_invalid_xml_in_zip_returns_error(
        self, parser: MstrParser, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad_xml.mstr"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("project.xml", "<<<not valid xml>>>")
        result = parser.parse(bad)
        assert result.errors, "Expected errors for invalid XML inside ZIP"


# ---------------------------------------------------------------------------
# ZIP-based fixture tests
# ---------------------------------------------------------------------------


class TestMstrParserSampleZip:
    def test_parse_returns_no_errors(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_source_file_set(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert result.source_file == str(sample_mstr)

    def test_tool_name_in_result(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert result.tool_name == "MicroStrategy"

    def test_file_type(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert result.file_type == "mstr"

    # --- DataSources ---

    def test_extracts_one_datasource(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert len(result.datasources) == 1

    def test_datasource_name(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert result.datasources[0].name == "SalesWarehouse"

    def test_datasource_type(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert result.datasources[0].connection_type == "ODBC"

    def test_datasource_tables(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        tables = result.datasources[0].tables
        assert len(tables) == 3, f"Expected 3 tables, got {len(tables)}: {tables}"
        assert set(tables) == {"fact_sales", "dim_customer", "dim_product"}

    # --- Fields ---

    def test_extracts_five_fields(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert len(result.fields) == 5, (
            f"Expected 5 fields (3 attributes + 2 metrics), got {len(result.fields)}"
        )

    def test_attribute_field_type(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        attribute_fields = [f for f in result.fields if f.field_type == "attribute"]
        assert len(attribute_fields) == 3

    def test_metric_field_type(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        metric_fields = [f for f in result.fields if f.field_type == "metric"]
        assert len(metric_fields) == 2

    def test_metric_formula(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        revenue = next(f for f in result.fields if f.name == "Revenue")
        assert revenue.formula == "Sum(fact_sales.amount)"

    def test_field_datasource_is_table_name(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        customer = next(f for f in result.fields if f.name == "Customer")
        assert customer.datasource == "dim_customer"

    # --- ReportElements ---

    def test_extracts_two_report_elements(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert len(result.report_elements) == 2

    def test_report_element_names(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        names = {e.name for e in result.report_elements}
        assert names == {"Sales Summary", "Regional Analysis"}

    def test_report_element_types(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        type_map = {e.name: e.element_type for e in result.report_elements}
        assert type_map["Sales Summary"] == "grid"
        assert type_map["Regional Analysis"] == "dashboard"

    def test_report_element_fields_used(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        sales_summary = next(
            e for e in result.report_elements if e.name == "Sales Summary"
        )
        assert set(sales_summary.fields_used) == {
            "Customer",
            "Region",
            "Revenue",
            "Order Count",
        }

    # --- Filters ---

    def test_extracts_one_filter(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert len(result.filters) == 1

    def test_filter_expression(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert "OrderDate" in result.filters[0].expression

    # --- Parameters ---

    def test_extracts_two_parameters(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert len(result.parameters) == 2

    def test_parameter_names(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        names = {p.name for p in result.parameters}
        assert names == {"StartDate", "EndDate"}

    def test_parameter_types(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        for p in result.parameters:
            assert p.data_type == "date"

    def test_parameter_default_value(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        start = next(p for p in result.parameters if p.name == "StartDate")
        assert start.default_value == "2024-01-01"

    # --- Metadata ---

    def test_metadata_project_name(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert result.metadata.get("project_name") == "Sales Analytics"

    def test_metadata_description(
        self, parser: MstrParser, sample_mstr: Path
    ) -> None:
        result = parser.parse(sample_mstr)
        assert result.metadata.get("description") == "Sales reporting project"


# ---------------------------------------------------------------------------
# Plain XML fallback tests
# ---------------------------------------------------------------------------


class TestMstrParserPlainXml:
    def test_plain_xml_parse_returns_no_errors(
        self, parser: MstrParser, plain_xml_mstr: Path
    ) -> None:
        result = parser.parse(plain_xml_mstr)
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_plain_xml_extracts_datasource(
        self, parser: MstrParser, plain_xml_mstr: Path
    ) -> None:
        result = parser.parse(plain_xml_mstr)
        assert len(result.datasources) == 1
        assert result.datasources[0].name == "SalesWarehouse"

    def test_plain_xml_extracts_fields(
        self, parser: MstrParser, plain_xml_mstr: Path
    ) -> None:
        result = parser.parse(plain_xml_mstr)
        assert len(result.fields) == 5

    def test_plain_xml_extracts_report_elements(
        self, parser: MstrParser, plain_xml_mstr: Path
    ) -> None:
        result = parser.parse(plain_xml_mstr)
        assert len(result.report_elements) == 2

    def test_plain_xml_extracts_parameters(
        self, parser: MstrParser, plain_xml_mstr: Path
    ) -> None:
        result = parser.parse(plain_xml_mstr)
        assert len(result.parameters) == 2

    def test_plain_xml_metadata(
        self, parser: MstrParser, plain_xml_mstr: Path
    ) -> None:
        result = parser.parse(plain_xml_mstr)
        assert result.metadata.get("project_name") == "Sales Analytics"
