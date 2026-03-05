"""Tests for the Power BI Desktop .pbix parser."""

from __future__ import annotations

import io
import json
import struct
import zipfile
from pathlib import Path

import pytest

from bi_extractor.parsers.microsoft.pbix_parser import PbixParser


def _build_data_mashup(m_code: str, metadata_xml: str = "") -> bytes:
    """Build a synthetic DataMashup binary blob for testing.

    DataMashup format: version(4) + pkg_len(4) + pkg_zip(N) +
                       perm_len(4) + perm(0) + meta_len(4) + meta_xml(K)
    """
    # Build inner ZIP with M formula
    inner_buf = io.BytesIO()
    with zipfile.ZipFile(inner_buf, "w") as inner_zf:
        inner_zf.writestr("Formulas/Section1.m", m_code.encode("utf-8"))
    pkg_data = inner_buf.getvalue()

    # Assemble binary blob
    parts = bytearray()
    parts += struct.pack("<I", 0)  # version
    parts += struct.pack("<I", len(pkg_data))
    parts += pkg_data
    parts += struct.pack("<I", 0)  # permissions length (empty)
    meta_bytes = metadata_xml.encode("utf-8") if metadata_xml else b""
    parts += struct.pack("<I", len(meta_bytes))
    parts += meta_bytes
    return bytes(parts)


def _create_sample_pbix(path: Path) -> Path:
    """Create a synthetic .pbix file for testing.

    Uses the real TMSL format where tables/relationships/dataSources live
    under a top-level ``"model"`` key, matching actual Power BI Desktop output.
    """
    model = {
        "name": "SalesModel",
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-US",
            "tables": [
                {
                    "name": "Sales",
                    "columns": [
                        {"name": "OrderID", "dataType": "int64", "sourceColumn": "order_id"},
                        {"name": "Amount", "dataType": "double", "sourceColumn": "amount"},
                        {"name": "OrderDate", "dataType": "dateTime", "sourceColumn": "order_date"},
                        {"name": "CustomerID", "dataType": "int64", "sourceColumn": "customer_id"},
                    ],
                    "measures": [
                        {"name": "Total Sales", "expression": "SUM(Sales[Amount])"},
                        {"name": "Order Count", "expression": "COUNTROWS(Sales)"},
                    ],
                    "partitions": [
                        {
                            "source": {
                                "type": "m",
                                "expression": 'let Source = Sql.Database("salesserver", "salesdb") in Source',
                            }
                        }
                    ],
                },
                {
                    "name": "Customers",
                    "columns": [
                        {"name": "CustomerID", "dataType": "int64", "sourceColumn": "customer_id"},
                        {"name": "CustomerName", "dataType": "string", "sourceColumn": "name"},
                        {"name": "Region", "dataType": "string", "sourceColumn": "region"},
                    ],
                    "measures": [],
                },
            ],
            "relationships": [
                {
                    "fromTable": "Sales",
                    "fromColumn": "CustomerID",
                    "toTable": "Customers",
                    "toColumn": "CustomerID",
                    "crossFilteringBehavior": 1,
                }
            ],
            "dataSources": [
                {
                    "name": "SqlServer salesdb",
                    "connectionString": "Data Source=salesserver;Initial Catalog=salesdb",
                }
            ],
        },
    }

    visual_config = json.dumps({
        "name": "visual1",
        "singleVisual": {
            "visualType": "barChart",
            "projections": {
                "Category": [{"queryRef": "Sales.Region"}],
                "Y": [{"queryRef": "Sales.Total Sales"}],
            },
        },
    })

    section_filters = json.dumps([
        {
            "name": "RegionFilter",
            "type": "Basic",
            "expression": {
                "Column": {
                    "Expression": {"SourceRef": {"Entity": "Sales"}},
                    "Property": "Region",
                }
            },
        }
    ])

    layout = {
        "sections": [
            {
                "name": "ReportSection1",
                "displayName": "Sales Overview",
                "visualContainers": [
                    {"config": visual_config},
                ],
                "filters": section_filters,
            }
        ],
    }

    connections = {
        "Connections": [
            {
                "Name": "SqlServer salesdb",
                "ConnectionString": "Data Source=salesserver;Initial Catalog=salesdb",
                "PbiServiceModelId": None,
            }
        ],
    }

    pbix_path = path / "sample.pbix"
    with zipfile.ZipFile(pbix_path, "w") as zf:
        zf.writestr("DataModelSchema", json.dumps(model))
        zf.writestr("Report/Layout", json.dumps(layout))
        zf.writestr("Connections", json.dumps(connections))
    return pbix_path


@pytest.fixture
def parser() -> PbixParser:
    return PbixParser()


@pytest.fixture
def sample_pbix(tmp_path: Path) -> Path:
    return _create_sample_pbix(tmp_path)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestPbixParserContract:
    def test_extensions(self, parser: PbixParser) -> None:
        assert ".pbix" in parser.extensions

    def test_tool_name(self, parser: PbixParser) -> None:
        assert parser.tool == "Power BI"

    def test_can_parse_pbix(self, parser: PbixParser) -> None:
        assert parser.can_parse(Path("report.pbix")) is True

    def test_cannot_parse_other_extension(self, parser: PbixParser) -> None:
        assert parser.can_parse(Path("report.twb")) is False

    def test_check_dependencies(self, parser: PbixParser) -> None:
        available, _ = parser.check_dependencies()
        assert available is True


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestPbixParserErrors:
    def test_missing_file_returns_error(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        result = parser.parse(tmp_path / "nonexistent.pbix")
        assert result.errors, "Expected errors for missing file"

    def test_corrupt_zip_returns_error(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        bad = tmp_path / "corrupt.pbix"
        bad.write_bytes(b"this is not a zip file at all")
        result = parser.parse(bad)
        assert result.errors, "Expected errors for corrupt ZIP"

    def test_empty_zip_returns_no_extraction_errors(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        empty_pbix = tmp_path / "empty.pbix"
        with zipfile.ZipFile(empty_pbix, "w"):
            pass  # write nothing
        result = parser.parse(empty_pbix)
        # No errors — missing entries are logged as warnings, not errors
        assert result.errors == []
        assert result.fields == []
        assert result.datasources == []

    def test_zip_missing_data_model_schema(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        """ZIP with only Report/Layout (no DataModelSchema) should still parse."""
        layout = {"sections": [{"name": "S1", "displayName": "Page 1", "visualContainers": []}]}
        pbix_path = tmp_path / "layout_only.pbix"
        with zipfile.ZipFile(pbix_path, "w") as zf:
            zf.writestr("Report/Layout", json.dumps(layout))
        result = parser.parse(pbix_path)
        assert result.errors == []
        assert result.fields == []
        assert len(result.report_elements) == 1

    def test_invalid_json_in_data_model_schema(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        pbix_path = tmp_path / "bad_model.pbix"
        with zipfile.ZipFile(pbix_path, "w") as zf:
            zf.writestr("DataModelSchema", "<<<not valid json>>>")
        result = parser.parse(pbix_path)
        assert result.errors, "Expected error for invalid JSON in DataModelSchema"


# ---------------------------------------------------------------------------
# Sample fixture tests
# ---------------------------------------------------------------------------


class TestPbixParserSample:
    def test_parse_returns_no_errors(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_source_file_set(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert result.source_file == str(sample_pbix)

    def test_tool_name_in_result(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert result.tool_name == "Power BI"

    def test_file_type_pbix(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert result.file_type == "pbix"

    # --- DataSources ---

    def test_extracts_datasources(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert len(result.datasources) >= 1

    def test_datasource_name(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        names = {ds.name for ds in result.datasources}
        assert "SqlServer salesdb" in names

    def test_datasource_connection_string(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        explicit_ds = next(
            ds for ds in result.datasources if ds.name == "SqlServer salesdb"
        )
        assert "salesdb" in explicit_ds.connection_string.lower()

    # --- Fields ---

    def test_extracts_fields(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        # 4 Sales columns + 2 Sales measures + 3 Customers columns = 9
        assert len(result.fields) == 9

    def test_field_types(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        columns = [f for f in result.fields if f.field_type == "column"]
        measures = [f for f in result.fields if f.field_type == "measure"]
        assert len(columns) == 7
        assert len(measures) == 2

    def test_measure_formula(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        total_sales = next(f for f in result.fields if f.name == "Total Sales")
        assert total_sales.formula == "SUM(Sales[Amount])"

    def test_field_datasource(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        sales_fields = [f for f in result.fields if f.datasource == "Sales"]
        customers_fields = [f for f in result.fields if f.datasource == "Customers"]
        assert len(sales_fields) == 6  # 4 columns + 2 measures
        assert len(customers_fields) == 3

    # --- Relationships ---

    def test_extracts_relationship(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert len(result.relationships) == 1

    def test_relationship_tables(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        rel = result.relationships[0]
        assert rel.left_table == "Sales"
        assert rel.right_table == "Customers"

    def test_relationship_fields(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        rel = result.relationships[0]
        assert rel.left_fields == ["CustomerID"]
        assert rel.right_fields == ["CustomerID"]

    def test_relationship_join_type(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert result.relationships[0].join_type == "oneDirection"

    # --- Report Elements ---

    def test_extracts_report_elements(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert len(result.report_elements) == 1

    def test_report_element_name(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert result.report_elements[0].name == "Sales Overview"

    def test_report_element_type_page(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert result.report_elements[0].element_type == "page"

    def test_report_element_fields_used(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        fields_used = set(result.report_elements[0].fields_used)
        assert "Sales.Region" in fields_used
        assert "Sales.Total Sales" in fields_used

    # --- Filters ---

    def test_extracts_filters(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert len(result.filters) >= 1

    def test_filter_name(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        names = {f.name for f in result.filters}
        assert "RegionFilter" in names

    # --- Metadata ---

    def test_model_name_in_metadata(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        result = parser.parse(sample_pbix)
        assert result.metadata.get("model_name") == "SalesModel"


# ---------------------------------------------------------------------------
# Legacy binary DataModel format detection
# ---------------------------------------------------------------------------


class TestPbixParserLegacyFormat:
    def test_legacy_without_mashup_has_no_fields(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        """PBIX with only binary DataModel (no DataMashup) yields no fields."""
        pbix_path = tmp_path / "legacy.pbix"
        with zipfile.ZipFile(pbix_path, "w") as zf:
            zf.writestr("DataModel", b"\x00\x01\x02binary data")
        result = parser.parse(pbix_path)
        assert result.fields == []
        assert result.metadata.get("legacy_format") == "true"

    def test_legacy_extracts_layout(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        """Legacy format should still extract Report/Layout if present."""
        layout = {
            "sections": [
                {"name": "S1", "displayName": "Overview", "visualContainers": []}
            ]
        }
        pbix_path = tmp_path / "legacy_with_layout.pbix"
        with zipfile.ZipFile(pbix_path, "w") as zf:
            zf.writestr("DataModel", b"\x00\x01\x02binary data")
            zf.writestr("Report/Layout", json.dumps(layout))
        result = parser.parse(pbix_path)
        assert len(result.report_elements) == 1
        assert result.report_elements[0].name == "Overview"

    def test_legacy_extracts_from_data_mashup(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        """Legacy format extracts fields and datasources from DataMashup."""
        m_code = (
            'section Section1;\n'
            'shared Orders = let\n'
            '    Source = Sql.Database("myserver.com", "salesdb")\n'
            'in Source;\n'
        )
        metadata_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<LocalPackageMetadataFile>'
            '<Items>'
            '<Item><ItemLocation><ItemType>Formula</ItemType>'
            '<ItemPath>Section1/Orders</ItemPath></ItemLocation>'
            '<StableEntries>'
            '<Entry Type="FillColumnNames" Value="s[&quot;OrderID&quot;,&quot;Amount&quot;,&quot;Date&quot;]" />'
            '</StableEntries></Item>'
            '</Items>'
            '</LocalPackageMetadataFile>'
        )
        mashup = _build_data_mashup(m_code, metadata_xml)

        pbix_path = tmp_path / "legacy_mashup.pbix"
        with zipfile.ZipFile(pbix_path, "w") as zf:
            zf.writestr("DataModel", b"\x00binary")
            zf.writestr("DataMashup", mashup)
        result = parser.parse(pbix_path)

        # Should extract datasource from M expression
        assert len(result.datasources) >= 1
        ds_names = {ds.name for ds in result.datasources}
        assert any("myserver.com" in n for n in ds_names)

        # Should extract columns from metadata XML
        assert len(result.fields) == 3
        field_names = {f.name for f in result.fields}
        assert field_names == {"OrderID", "Amount", "Date"}

        # Should extract table name from M shared declaration
        assert "Orders" in result.metadata.get("mashup_tables", [])

    def test_legacy_mashup_datasource_extracted(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        """DataMashup M code should yield datasources for legacy files."""
        m_code = (
            'section Section1;\n'
            'shared Sales = let\n'
            '    Source = OData.Feed("https://api.example.com/sales")\n'
            'in Source;\n'
        )
        mashup = _build_data_mashup(m_code)

        pbix_path = tmp_path / "legacy_odata.pbix"
        with zipfile.ZipFile(pbix_path, "w") as zf:
            zf.writestr("DataModel", b"\x00binary")
            zf.writestr("DataMashup", mashup)
        result = parser.parse(pbix_path)

        assert len(result.datasources) >= 1
        assert any("OData" in ds.connection_type for ds in result.datasources)


# ---------------------------------------------------------------------------
# Connections entry tests
# ---------------------------------------------------------------------------


class TestPbixParserConnections:
    def test_connections_entry_extracted(
        self, parser: PbixParser, tmp_path: Path
    ) -> None:
        """Connections entry should yield datasources."""
        connections = {
            "Connections": [
                {
                    "Name": "MyServer",
                    "ConnectionString": "Data Source=srv;Initial Catalog=mydb",
                }
            ]
        }
        pbix_path = tmp_path / "conn.pbix"
        with zipfile.ZipFile(pbix_path, "w") as zf:
            zf.writestr("DataModelSchema", json.dumps({"name": "M"}))
            zf.writestr("Connections", json.dumps(connections))
        result = parser.parse(pbix_path)
        assert len(result.datasources) >= 1
        names = {ds.name for ds in result.datasources}
        assert "MyServer" in names

    def test_connections_does_not_duplicate_model_datasources(
        self, parser: PbixParser, sample_pbix: Path
    ) -> None:
        """If datasource already exists from model, Connections should not duplicate."""
        result = parser.parse(sample_pbix)
        ds_names = [ds.name for ds in result.datasources]
        assert ds_names.count("SqlServer salesdb") == 1
