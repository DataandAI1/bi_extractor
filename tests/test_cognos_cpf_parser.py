"""Tests for the IBM Cognos Framework Manager .cpf parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from bi_extractor.parsers.cognos.cpf_parser import CognosCpfParser


@pytest.fixture
def parser() -> CognosCpfParser:
    return CognosCpfParser()


@pytest.fixture
def sample_cpf(cognos_fixtures_dir: Path) -> Path:
    return cognos_fixtures_dir / "sample.cpf"


class TestCognosCpfParserContract:
    def test_extensions(self, parser: CognosCpfParser) -> None:
        assert ".cpf" in parser.extensions

    def test_tool_name(self, parser: CognosCpfParser) -> None:
        assert parser.tool == "IBM Cognos Analytics"

    def test_can_parse_cpf(self, parser: CognosCpfParser) -> None:
        assert parser.can_parse(Path("model.cpf")) is True

    def test_cannot_parse_other_extension(self, parser: CognosCpfParser) -> None:
        assert parser.can_parse(Path("report.twb")) is False

    def test_check_dependencies(self, parser: CognosCpfParser) -> None:
        available, _ = parser.check_dependencies()
        assert available is True


class TestCognosCpfParserMissingFile:
    def test_missing_file_returns_error(
        self, parser: CognosCpfParser, tmp_path: Path
    ) -> None:
        result = parser.parse(tmp_path / "nonexistent.cpf")
        assert result.errors, "Expected errors for missing file"

    def test_invalid_xml_returns_error(
        self, parser: CognosCpfParser, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.cpf"
        bad.write_text("<<<not valid xml>>>", encoding="utf-8")
        result = parser.parse(bad)
        assert result.errors, "Expected errors for invalid XML"

    def test_empty_project_returns_no_errors(
        self, parser: CognosCpfParser, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty.cpf"
        empty.write_text('<?xml version="1.0"?><project name="Empty"/>', encoding="utf-8")
        result = parser.parse(empty)
        assert result.errors == []
        assert result.metadata.get("project_name") == "Empty"


class TestCognosCpfParserSampleCpf:
    def test_parse_returns_no_errors(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_source_file_set(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.source_file == str(sample_cpf)

    def test_tool_name_in_result(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.tool_name == "IBM Cognos Analytics"

    def test_file_type_cpf(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.file_type == "cpf"

    # --- DataSources ---

    def test_extracts_one_datasource(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert len(result.datasources) == 1

    def test_datasource_name(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.datasources[0].name == "SalesDB"

    def test_datasource_connection_type(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.datasources[0].connection_type == "ODBC"

    def test_datasource_connection_string(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert "SalesDB" in result.datasources[0].connection_string

    def test_datasource_schema(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.datasources[0].schema == "dbo"

    def test_datasource_tables(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        tables = result.datasources[0].tables
        assert len(tables) == 3, f"Expected 3 tables, got {len(tables)}: {tables}"
        assert set(tables) == {"orders", "customers", "products"}

    # --- Fields (query items) ---

    def test_extracts_seven_fields(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert len(result.fields) == 7

    def test_field_names(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        names = {f.name for f in result.fields}
        assert "OrderID" in names
        assert "CustomerName" in names
        assert "Amount" in names
        assert "Region" in names

    def test_field_data_types(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        type_map = {f.name: f.data_type for f in result.fields}
        assert type_map["OrderID"] == "integer"
        assert type_map["CustomerName"] == "varchar"
        assert type_map["Amount"] == "decimal"

    def test_field_datasource_is_query_subject(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        orders_fields = [f for f in result.fields if f.datasource == "Orders"]
        assert len(orders_fields) == 4

    def test_field_formula(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        order_id = next(f for f in result.fields if f.name == "OrderID")
        assert order_id.formula == "[orders].[order_id]"

    def test_field_alias(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        cust_name = next(f for f in result.fields if f.name == "CustomerName")
        assert cust_name.alias == "Customer Name"

    # --- Parameters ---

    def test_extracts_two_parameters(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert len(result.parameters) == 2

    def test_parameter_names(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        names = {p.name for p in result.parameters}
        assert names == {"p_startDate", "p_region"}

    def test_parameter_data_type(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        start_date = next(p for p in result.parameters if p.name == "p_startDate")
        assert start_date.data_type == "date"

    def test_parameter_default_value(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        start_date = next(p for p in result.parameters if p.name == "p_startDate")
        assert start_date.default_value == "2024-01-01"

    def test_parameter_prompt_text(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        start_date = next(p for p in result.parameters if p.name == "p_startDate")
        assert start_date.prompt_text == "Start Date"

    # --- Relationships ---

    def test_extracts_one_relationship(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert len(result.relationships) == 1

    def test_relationship_tables(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        rel = result.relationships[0]
        assert rel.left_table == "Orders"
        assert rel.right_table == "Customers"

    def test_relationship_join_type(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.relationships[0].join_type == "inner"

    def test_relationship_fields(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        rel = result.relationships[0]
        assert rel.left_fields == ["CustomerID"]
        assert rel.right_fields == ["CustomerID"]

    # --- Filters ---

    def test_extracts_one_filter(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert len(result.filters) == 1

    def test_filter_name(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.filters[0].name == "DateRange"

    def test_filter_expression(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert "p_startDate" in result.filters[0].expression

    def test_filter_scope(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.filters[0].scope == "report"

    # --- Report Elements (query subjects) ---

    def test_extracts_two_report_elements(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert len(result.report_elements) == 2

    def test_report_element_names(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        names = {e.name for e in result.report_elements}
        assert names == {"Orders", "Customers"}

    def test_report_element_type(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        for el in result.report_elements:
            assert el.element_type == "querySubject"

    def test_report_element_fields_used(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        orders = next(e for e in result.report_elements if e.name == "Orders")
        assert set(orders.fields_used) == {"OrderID", "OrderDate", "Amount", "CustomerID"}

    # --- Metadata ---

    def test_project_name_in_metadata(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.metadata.get("project_name") == "SalesModel"

    def test_description_in_metadata(
        self, parser: CognosCpfParser, sample_cpf: Path
    ) -> None:
        result = parser.parse(sample_cpf)
        assert result.metadata.get("description") == "Sales analytics metadata model"
