"""Tests for the Oracle BI Publisher .xdo / .xdoz parser."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from bi_extractor.parsers.oracle.xdo_parser import OracleXdoParser


@pytest.fixture
def parser() -> OracleXdoParser:
    return OracleXdoParser()


@pytest.fixture
def sample_xdo(oracle_fixtures_dir: Path) -> Path:
    return oracle_fixtures_dir / "sample.xdo"


@pytest.fixture
def sample_xdoz(oracle_fixtures_dir: Path, tmp_path: Path) -> Path:
    """Create a .xdoz by zipping the sample .xdo fixture."""
    xdo_path = oracle_fixtures_dir / "sample.xdo"
    xdoz_path = tmp_path / "sample.xdoz"
    with zipfile.ZipFile(xdoz_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(xdo_path, arcname="sample.xdo")
    return xdoz_path


class TestOracleXdoParserContract:
    def test_extensions(self, parser: OracleXdoParser) -> None:
        assert ".xdo" in parser.extensions
        assert ".xdoz" in parser.extensions

    def test_tool_name(self, parser: OracleXdoParser) -> None:
        assert parser.tool == "Oracle BI Publisher"

    def test_can_parse_xdo(self, parser: OracleXdoParser) -> None:
        assert parser.can_parse(Path("template.xdo")) is True

    def test_can_parse_xdoz(self, parser: OracleXdoParser) -> None:
        assert parser.can_parse(Path("template.xdoz")) is True

    def test_cannot_parse_other_extension(self, parser: OracleXdoParser) -> None:
        assert parser.can_parse(Path("report.twb")) is False

    def test_check_dependencies(self, parser: OracleXdoParser) -> None:
        available, _ = parser.check_dependencies()
        assert available is True


class TestOracleXdoParserMissingFile:
    def test_missing_xdo_returns_error(
        self, parser: OracleXdoParser, tmp_path: Path
    ) -> None:
        result = parser.parse(tmp_path / "nonexistent.xdo")
        assert result.errors, "Expected errors for missing file"

    def test_invalid_xml_returns_error(
        self, parser: OracleXdoParser, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.xdo"
        bad.write_text("<<<not valid xml>>>", encoding="utf-8")
        result = parser.parse(bad)
        assert result.errors, "Expected errors for invalid XML"

    def test_bad_zip_returns_error(
        self, parser: OracleXdoParser, tmp_path: Path
    ) -> None:
        bad = tmp_path / "bad.xdoz"
        bad.write_bytes(b"not a zip file at all")
        result = parser.parse(bad)
        assert result.errors, "Expected errors for bad ZIP"

    def test_zip_without_xdo_returns_error(
        self, parser: OracleXdoParser, tmp_path: Path
    ) -> None:
        empty_zip = tmp_path / "empty.xdoz"
        with zipfile.ZipFile(empty_zip, "w") as zf:
            zf.writestr("readme.txt", "no xdo here")
        result = parser.parse(empty_zip)
        assert result.errors, "Expected errors when ZIP has no .xdo entry"


class TestOracleXdoParserSampleXdo:
    def test_parse_returns_no_errors(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_source_file_set(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert result.source_file == str(sample_xdo)

    def test_tool_name_in_result(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert result.tool_name == "Oracle BI Publisher"

    def test_file_type_xdo(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert result.file_type == ".xdo"

    # --- DataSources ---

    def test_extracts_one_datasource(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert len(result.datasources) == 1

    def test_datasource_name(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert result.datasources[0].name == "SalesDS"

    def test_datasource_connection_type(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert result.datasources[0].connection_type == "JDBC"

    # --- Parameters ---

    def test_extracts_two_parameters(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert len(result.parameters) == 2

    def test_parameter_names(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        names = {p.name for p in result.parameters}
        assert names == {"p_year", "p_region"}

    def test_parameter_data_type(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        year = next(p for p in result.parameters if p.name == "p_year")
        assert year.data_type == "NUMBER"

    def test_parameter_default_value(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        year = next(p for p in result.parameters if p.name == "p_year")
        assert year.default_value == "2024"

    def test_parameter_prompt_text(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        year = next(p for p in result.parameters if p.name == "p_year")
        assert year.prompt_text == "Fiscal Year"

    # --- Fields ---

    def test_extracts_four_fields(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert len(result.fields) == 4

    def test_field_names(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        names = {f.name for f in result.fields}
        assert names == {"ORDER_ID", "CUSTOMER_NAME", "AMOUNT", "REGION"}

    def test_field_data_types(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        type_map = {f.name: f.data_type for f in result.fields}
        assert type_map["ORDER_ID"] == "NUMBER"
        assert type_map["CUSTOMER_NAME"] == "VARCHAR2"

    # --- Report Elements ---

    def test_extracts_group_element(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert len(result.report_elements) == 1
        assert result.report_elements[0].name == "G_ORDERS"
        assert result.report_elements[0].element_type == "group"

    # --- SQL queries in metadata ---

    def test_sql_query_extracted(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert "sql_queries" in result.metadata
        assert len(result.metadata["sql_queries"]) >= 1

    def test_sql_query_content(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        sql_text = next(iter(result.metadata["sql_queries"].values()))
        assert "SELECT" in sql_text.upper()

    def test_sql_query_key_is_name_attribute(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert "Q_ORDERS" in result.metadata["sql_queries"]

    # --- Metadata ---

    def test_template_name_in_metadata(
        self, parser: OracleXdoParser, sample_xdo: Path
    ) -> None:
        result = parser.parse(sample_xdo)
        assert result.metadata.get("template_name") == "SalesReport"


class TestOracleXdoParserSampleXdoz:
    def test_parse_xdoz_returns_no_errors(
        self, parser: OracleXdoParser, sample_xdoz: Path
    ) -> None:
        result = parser.parse(sample_xdoz)
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_xdoz_file_type(
        self, parser: OracleXdoParser, sample_xdoz: Path
    ) -> None:
        result = parser.parse(sample_xdoz)
        assert result.file_type == ".xdoz"

    def test_xdoz_extracts_datasource(
        self, parser: OracleXdoParser, sample_xdoz: Path
    ) -> None:
        result = parser.parse(sample_xdoz)
        assert len(result.datasources) == 1
        assert result.datasources[0].name == "SalesDS"

    def test_xdoz_extracts_parameters(
        self, parser: OracleXdoParser, sample_xdoz: Path
    ) -> None:
        result = parser.parse(sample_xdoz)
        assert len(result.parameters) == 2

    def test_xdoz_extracts_fields(
        self, parser: OracleXdoParser, sample_xdoz: Path
    ) -> None:
        result = parser.parse(sample_xdoz)
        assert len(result.fields) == 4

    def test_xdoz_extracts_sql(
        self, parser: OracleXdoParser, sample_xdoz: Path
    ) -> None:
        result = parser.parse(sample_xdoz)
        assert "sql_queries" in result.metadata
        assert "Q_ORDERS" in result.metadata["sql_queries"]
