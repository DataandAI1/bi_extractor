"""Tests for the Eclipse BIRT .rptdesign parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from bi_extractor.parsers.eclipse.birt_parser import BirtParser


@pytest.fixture
def parser() -> BirtParser:
    return BirtParser()


@pytest.fixture
def sample_rptdesign(birt_fixtures_dir: Path) -> Path:
    return birt_fixtures_dir / "sample.rptdesign"


class TestBirtParserContract:
    def test_extensions(self, parser: BirtParser) -> None:
        assert ".rptdesign" in parser.extensions

    def test_tool_name(self, parser: BirtParser) -> None:
        assert parser.tool == "BIRT"

    def test_can_parse_rptdesign(self, parser: BirtParser) -> None:
        assert parser.can_parse(Path("report.rptdesign")) is True

    def test_cannot_parse_other_extension(self, parser: BirtParser) -> None:
        assert parser.can_parse(Path("report.twb")) is False

    def test_check_dependencies(self, parser: BirtParser) -> None:
        available, _ = parser.check_dependencies()
        assert available is True


class TestBirtParserMissingFile:
    def test_missing_file_returns_error(self, parser: BirtParser, tmp_path: Path) -> None:
        result = parser.parse(tmp_path / "nonexistent.rptdesign")
        assert result.errors, "Expected errors for missing file"
        assert result.datasources == []
        assert result.fields == []

    def test_invalid_xml_returns_error(self, parser: BirtParser, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.rptdesign"
        bad_file.write_text("<<<not valid xml>>>", encoding="utf-8")
        result = parser.parse(bad_file)
        assert result.errors, "Expected errors for invalid XML"


class TestBirtParserSampleFile:
    def test_parse_returns_result(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_source_file_set(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert result.source_file == str(sample_rptdesign)

    def test_tool_name_in_result(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert result.tool_name == "BIRT"

    def test_file_type_in_result(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert result.file_type == ".rptdesign"

    # --- DataSources ---

    def test_extracts_one_datasource(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert len(result.datasources) == 1

    def test_datasource_name(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert result.datasources[0].name == "SalesDB"

    def test_datasource_connection_type(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        ds = result.datasources[0]
        assert "jdbc" in ds.connection_type.lower()

    def test_datasource_connection_string(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        ds = result.datasources[0]
        assert "mysql" in ds.connection_string.lower()

    def test_datasource_database(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert result.datasources[0].database == "sales"

    # --- Fields ---

    def test_extracts_four_fields(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert len(result.fields) == 4

    def test_field_names(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        names = {f.name for f in result.fields}
        assert names == {"order_id", "customer_name", "amount", "region"}

    def test_field_data_types(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        type_map = {f.name: f.data_type for f in result.fields}
        assert type_map["order_id"] == "integer"
        assert type_map["customer_name"] == "string"
        assert type_map["amount"] == "decimal"

    def test_field_datasource_ref(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        for f in result.fields:
            assert f.datasource == "SalesDataSet"

    # --- Parameters ---

    def test_extracts_two_parameters(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert len(result.parameters) == 2

    def test_parameter_names(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        names = {p.name for p in result.parameters}
        assert names == {"reportYear", "regionFilter"}

    def test_parameter_data_type(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        year_param = next(p for p in result.parameters if p.name == "reportYear")
        assert year_param.data_type == "integer"

    def test_parameter_default_value(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        year_param = next(p for p in result.parameters if p.name == "reportYear")
        assert year_param.default_value == "2024"

    def test_parameter_prompt_text(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        year_param = next(p for p in result.parameters if p.name == "reportYear")
        assert year_param.prompt_text == "Report Year"

    # --- Report Elements (body) ---

    def test_extracts_three_body_elements(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert len(result.report_elements) == 3

    def test_body_element_types(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        types = {e.element_type for e in result.report_elements}
        assert types == {"grid", "table", "label"}

    def test_body_element_names(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        names = {e.name for e in result.report_elements}
        assert "headerGrid" in names
        assert "salesTable" in names
        assert "footerLabel" in names

    # --- SQL queries in metadata ---

    def test_sql_query_extracted(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        assert "sql_queries" in result.metadata
        assert "SalesDataSet" in result.metadata["sql_queries"]

    def test_sql_query_content(
        self, parser: BirtParser, sample_rptdesign: Path
    ) -> None:
        result = parser.parse(sample_rptdesign)
        sql = result.metadata["sql_queries"]["SalesDataSet"]
        assert "SELECT" in sql.upper()
        assert "orders" in sql.lower()
