"""Tests for the QlikView Data .qvd parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from bi_extractor.parsers.qlik.qvd_parser import QvdParser


@pytest.fixture
def parser() -> QvdParser:
    return QvdParser()


def _create_sample_qvd(path: Path) -> Path:
    """Create a synthetic .qvd file with XML header and dummy binary data."""
    header = '''<?xml version="1.0" encoding="UTF-8" ?>
<QvdTableHeader>
  <QvBuildNo>50645</QvBuildNo>
  <CreatorDoc>SalesApp.qvw</CreatorDoc>
  <CreateUtcTime>2024-01-15 10:30:00</CreateUtcTime>
  <TableName>Sales</TableName>
  <Fields>
    <QvdFieldHeader>
      <FieldName>OrderID</FieldName>
      <NumberFormat><Type>1</Type></NumberFormat>
      <NoOfSymbols>1000</NoOfSymbols>
      <Comment>Order identifier</Comment>
    </QvdFieldHeader>
    <QvdFieldHeader>
      <FieldName>Amount</FieldName>
      <NumberFormat><Type>2</Type></NumberFormat>
      <NoOfSymbols>500</NoOfSymbols>
    </QvdFieldHeader>
    <QvdFieldHeader>
      <FieldName>OrderDate</FieldName>
      <NumberFormat><Type>4</Type></NumberFormat>
      <NoOfSymbols>365</NoOfSymbols>
    </QvdFieldHeader>
    <QvdFieldHeader>
      <FieldName>CustomerName</FieldName>
      <NumberFormat><Type>7</Type></NumberFormat>
      <NoOfSymbols>200</NoOfSymbols>
    </QvdFieldHeader>
  </Fields>
  <NoOfRecords>1000</NoOfRecords>
  <RecordByteSize>32</RecordByteSize>
  <Comment>Sales transaction data</Comment>
</QvdTableHeader>'''
    qvd_path = path / "sample.qvd"
    with open(qvd_path, "wb") as f:
        f.write(header.encode("utf-8"))
        f.write(b"\x00")  # null byte separator
        f.write(b"\x00" * 64)  # dummy binary data
    return qvd_path


@pytest.fixture
def sample_qvd(tmp_path: Path) -> Path:
    return _create_sample_qvd(tmp_path)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestQvdParserContract:
    def test_extensions(self, parser: QvdParser) -> None:
        assert ".qvd" in parser.extensions

    def test_tool(self, parser: QvdParser) -> None:
        assert parser.tool == "QlikView"

    def test_can_parse_qvd(self, parser: QvdParser) -> None:
        assert parser.can_parse(Path("data.qvd")) is True

    def test_cannot_parse_other_extension(self, parser: QvdParser) -> None:
        assert parser.can_parse(Path("report.twb")) is False

    def test_check_dependencies(self, parser: QvdParser) -> None:
        available, _ = parser.check_dependencies()
        assert available is True


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestQvdParserErrors:
    def test_missing_file_returns_error(
        self, parser: QvdParser, tmp_path: Path
    ) -> None:
        result = parser.parse(tmp_path / "nonexistent.qvd")
        assert result.errors, "Expected errors for missing file"

    def test_empty_file_returns_error(
        self, parser: QvdParser, tmp_path: Path
    ) -> None:
        empty = tmp_path / "empty.qvd"
        empty.write_bytes(b"")
        result = parser.parse(empty)
        assert result.errors, "Expected errors for empty file"

    def test_file_without_xml_header_returns_error(
        self, parser: QvdParser, tmp_path: Path
    ) -> None:
        no_header = tmp_path / "no_header.qvd"
        no_header.write_bytes(b"\x00" * 128)  # pure binary, no XML header
        result = parser.parse(no_header)
        assert result.errors, "Expected errors for file without XML header"

    def test_corrupt_xml_header_returns_error(
        self, parser: QvdParser, tmp_path: Path
    ) -> None:
        corrupt = tmp_path / "corrupt.qvd"
        # Ends with the expected closing tag but XML itself is malformed
        bad_xml = b"<<<not xml>>></QvdTableHeader>"
        corrupt.write_bytes(bad_xml)
        result = parser.parse(corrupt)
        assert result.errors, "Expected errors for corrupt XML header"


# ---------------------------------------------------------------------------
# Sample file tests
# ---------------------------------------------------------------------------


class TestQvdParserSample:
    def test_parse_returns_no_errors(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.errors == [], f"Unexpected errors: {result.errors}"

    def test_source_file_set(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.source_file == str(sample_qvd)

    def test_tool_name(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.tool_name == "QlikView"

    def test_file_type(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.file_type == "qvd"

    # --- DataSource ---

    def test_extracts_one_datasource(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert len(result.datasources) == 1

    def test_datasource_name(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.datasources[0].name == "Sales"

    def test_datasource_connection_type(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.datasources[0].connection_type == "QVD"

    def test_datasource_tables(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.datasources[0].tables == ["Sales"]

    # --- Fields ---

    def test_extracts_four_fields(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert len(result.fields) == 4

    def test_field_names(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        names = [f.name for f in result.fields]
        assert names == ["OrderID", "Amount", "OrderDate", "CustomerName"]

    def test_field_data_types(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        type_map = {f.name: f.data_type for f in result.fields}
        assert type_map["OrderID"] == "integer"
        assert type_map["Amount"] == "float"
        assert type_map["OrderDate"] == "date"
        assert type_map["CustomerName"] == "string"

    def test_field_alias(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        order_id = next(f for f in result.fields if f.name == "OrderID")
        assert order_id.alias == "Order identifier"

    def test_field_alias_empty_when_no_comment(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        amount = next(f for f in result.fields if f.name == "Amount")
        assert amount.alias == ""

    def test_field_datasource(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        for f in result.fields:
            assert f.datasource == "Sales"

    def test_field_type_is_column(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        for f in result.fields:
            assert f.field_type == "column"

    # --- Metadata ---

    def test_metadata_record_count(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.metadata["record_count"] == 1000

    def test_metadata_creator_doc(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.metadata["creator_doc"] == "SalesApp.qvw"

    def test_metadata_table_name(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.metadata["table_name"] == "Sales"

    def test_metadata_qv_build_no(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.metadata["qv_build_no"] == "50645"

    def test_metadata_create_time(
        self, parser: QvdParser, sample_qvd: Path
    ) -> None:
        result = parser.parse(sample_qvd)
        assert result.metadata["create_time"] == "2024-01-15 10:30:00"
