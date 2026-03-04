"""Tests for the Tableau TWB/TWBX parser."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from bi_extractor.parsers.tableau.twb_parser import TableauTwbParser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "tableau"
SAMPLE_TWB = FIXTURES_DIR / "sample.twb"


@pytest.fixture()
def parser() -> TableauTwbParser:
    return TableauTwbParser()


# ---------------------------------------------------------------------------
# Class-level attribute tests
# ---------------------------------------------------------------------------


def test_extensions() -> None:
    assert TableauTwbParser.extensions == [".twb", ".twbx"]


def test_tool_name() -> None:
    assert TableauTwbParser.tool == "Tableau"


def test_can_parse_twb(parser: TableauTwbParser, tmp_path: Path) -> None:
    f = tmp_path / "report.twb"
    f.touch()
    assert parser.can_parse(f) is True


def test_can_parse_twbx(parser: TableauTwbParser, tmp_path: Path) -> None:
    f = tmp_path / "report.twbx"
    f.touch()
    assert parser.can_parse(f) is True


def test_cannot_parse_other(parser: TableauTwbParser, tmp_path: Path) -> None:
    f = tmp_path / "report.pbix"
    f.touch()
    assert parser.can_parse(f) is False


# ---------------------------------------------------------------------------
# Parsing the sample fixture
# ---------------------------------------------------------------------------


def test_parse_returns_extraction_result(parser: TableauTwbParser) -> None:
    result = parser.parse(SAMPLE_TWB)
    assert result.tool_name == "Tableau"
    assert result.source_file == str(SAMPLE_TWB)
    assert result.file_type == "twb"
    assert result.errors == []


def test_parse_datasources(parser: TableauTwbParser) -> None:
    result = parser.parse(SAMPLE_TWB)
    ds_names = {ds.name for ds in result.datasources}
    assert "salesdata" in ds_names
    assert "customerdata" in ds_names


def test_parse_datasource_connection_type(parser: TableauTwbParser) -> None:
    result = parser.parse(SAMPLE_TWB)
    sales_ds = next(ds for ds in result.datasources if ds.name == "salesdata")
    assert sales_ds.connection_type == "sqlserver"
    assert sales_ds.alias == "Sales Data"


def test_parse_datasource_connection_string(parser: TableauTwbParser) -> None:
    result = parser.parse(SAMPLE_TWB)
    customer_ds = next(ds for ds in result.datasources if ds.name == "customerdata")
    assert customer_ds.connection_type == "excel-direct"
    # filename attribute is used as connection_string
    assert "customers.xlsx" in customer_ds.connection_string


def test_parse_fields_extracted(parser: TableauTwbParser) -> None:
    result = parser.parse(SAMPLE_TWB)
    field_names = {f.name for f in result.fields}
    assert "[Region]" in field_names
    assert "[Revenue]" in field_names
    assert "[CustomerID]" in field_names
    assert "[Segment]" in field_names


def test_parse_field_types(parser: TableauTwbParser) -> None:
    result = parser.parse(SAMPLE_TWB)
    by_name = {f.name: f for f in result.fields}

    region = by_name["[Region]"]
    assert region.field_type == "Dimension"
    assert region.data_type == "string"
    assert region.role == "dimension"

    revenue = by_name["[Revenue]"]
    assert revenue.field_type == "Aggregated Measure"
    assert revenue.data_type == "real"


def test_parse_calculated_field(parser: TableauTwbParser) -> None:
    result = parser.parse(SAMPLE_TWB)
    by_name = {f.name: f for f in result.fields}

    profit = by_name["[Calculation_1234567890123]"]
    assert profit.field_type in ("Calculated Field", "Table Calculation")
    assert profit.original_formula == "SUM([Revenue]) / SUM([Cost])"
    assert profit.alias == "Profit Ratio"


def test_parse_formula_id_resolution(parser: TableauTwbParser) -> None:
    """[Calculation_1234567890123] inside [Margin] formula should be resolved."""
    result = parser.parse(SAMPLE_TWB)
    by_name = {f.name: f for f in result.fields}

    margin = by_name["[Margin]"]
    # The ID 1234567890123 maps to caption 'Profit Ratio'
    assert "[Profit Ratio]" in margin.formula
    assert margin.formula_status in ("Success", "Partially Resolved")


def test_parse_worksheets(parser: TableauTwbParser) -> None:
    result = parser.parse(SAMPLE_TWB)
    ws_names = {re.name for re in result.report_elements}
    assert "Revenue Overview" in ws_names
    assert "Customer Breakdown" in ws_names


def test_parse_worksheet_fields(parser: TableauTwbParser) -> None:
    result = parser.parse(SAMPLE_TWB)
    by_name = {re.name: re for re in result.report_elements}

    revenue_ws = by_name["Revenue Overview"]
    assert "[Region]" in revenue_ws.fields_used
    assert "[Revenue]" in revenue_ws.fields_used

    breakdown_ws = by_name["Customer Breakdown"]
    assert "[CustomerID]" in breakdown_ws.fields_used
    assert "[Segment]" in breakdown_ws.fields_used


def test_parse_worksheet_field_deduplication(parser: TableauTwbParser) -> None:
    """[Revenue] appears in Customer Breakdown from two datasources — only once."""
    result = parser.parse(SAMPLE_TWB)
    by_name = {re.name: re for re in result.report_elements}
    breakdown_ws = by_name["Customer Breakdown"]
    assert breakdown_ws.fields_used.count("[Revenue]") == 1


# ---------------------------------------------------------------------------
# TWBX (zip) handling
# ---------------------------------------------------------------------------


def test_parse_twbx(parser: TableauTwbParser, tmp_path: Path) -> None:
    """Pack sample.twb into a .twbx archive and verify the parser handles it."""
    twbx_path = tmp_path / "sample.twbx"
    with zipfile.ZipFile(twbx_path, "w") as zf:
        zf.write(SAMPLE_TWB, arcname="sample.twb")

    result = parser.parse(twbx_path)
    assert result.errors == []
    assert result.file_type == "twbx"
    ds_names = {ds.name for ds in result.datasources}
    assert "salesdata" in ds_names


# ---------------------------------------------------------------------------
# Error / edge-case handling
# ---------------------------------------------------------------------------


def test_parse_empty_file_no_raise(parser: TableauTwbParser, tmp_path: Path) -> None:
    """An empty file must not raise — error goes into result.errors."""
    empty = tmp_path / "empty.twb"
    empty.write_bytes(b"")
    result = parser.parse(empty)
    assert len(result.errors) > 0


def test_parse_corrupt_xml_no_raise(parser: TableauTwbParser, tmp_path: Path) -> None:
    """Corrupt XML must not raise — error goes into result.errors."""
    corrupt = tmp_path / "corrupt.twb"
    corrupt.write_bytes(b"<workbook><unclosed>")
    result = parser.parse(corrupt)
    assert len(result.errors) > 0


def test_parse_nonexistent_file_no_raise(parser: TableauTwbParser, tmp_path: Path) -> None:
    """A missing file must not raise."""
    missing = tmp_path / "ghost.twb"
    result = parser.parse(missing)
    assert len(result.errors) > 0


def test_parse_corrupt_twbx_no_raise(parser: TableauTwbParser, tmp_path: Path) -> None:
    """A corrupt zip must not raise."""
    bad_zip = tmp_path / "bad.twbx"
    bad_zip.write_bytes(b"not a zip")
    result = parser.parse(bad_zip)
    assert len(result.errors) > 0


def test_parse_minimal_twb_no_errors(parser: TableauTwbParser, tmp_path: Path) -> None:
    """Minimal well-formed TWB with no datasources or worksheets should succeed."""
    minimal = tmp_path / "minimal.twb"
    minimal.write_text(
        "<?xml version='1.0' encoding='utf-8'?><workbook></workbook>",
        encoding="utf-8",
    )
    result = parser.parse(minimal)
    assert result.errors == []
    assert result.fields == []
    assert result.datasources == []
    assert result.report_elements == []
