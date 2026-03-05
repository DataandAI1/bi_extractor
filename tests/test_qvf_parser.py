"""Tests for the Qlik Sense application (.qvf) parser."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from bi_extractor.parsers.qlik.qvf_parser import QvfParser


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _create_sample_qvf(path: Path) -> Path:
    """Create a synthetic .qvf file (SQLite database) for testing."""
    qvf_path = path / "sample.qvf"
    conn = sqlite3.connect(str(qvf_path))
    cursor = conn.cursor()

    # Create tables matching QVF internal structure
    cursor.execute("""
        CREATE TABLE qlik_tables (
            name TEXT PRIMARY KEY,
            source TEXT,
            fields TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE qlik_fields (
            name TEXT,
            src_table TEXT,
            data_type TEXT,
            tags TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE qlik_objects (
            id TEXT PRIMARY KEY,
            type TEXT,
            data TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE qlik_load_script (
            script TEXT
        )
    """)

    # Insert sample tables
    cursor.execute(
        "INSERT INTO qlik_tables VALUES (?, ?, ?)",
        ("Sales", "lib://DataFiles/sales.csv", "OrderID,Amount,OrderDate,CustomerID"),
    )
    cursor.execute(
        "INSERT INTO qlik_tables VALUES (?, ?, ?)",
        ("Customers", "lib://DataFiles/customers.xlsx", "CustomerID,CustomerName,Region"),
    )

    # Insert sample fields
    for field_name, table, dtype, tags in [
        ("OrderID", "Sales", "integer", "$numeric"),
        ("Amount", "Sales", "number", "$numeric,$money"),
        ("OrderDate", "Sales", "date", "$timestamp"),
        ("CustomerID", "Sales", "integer", "$numeric,$key"),
        ("CustomerID", "Customers", "integer", "$numeric,$key"),
        ("CustomerName", "Customers", "text", "$text"),
        ("Region", "Customers", "text", "$text"),
    ]:
        cursor.execute(
            "INSERT INTO qlik_fields VALUES (?, ?, ?, ?)",
            (field_name, table, dtype, tags),
        )

    # Insert sample objects (sheets and measures)
    sheet_data = json.dumps({
        "title": "Sales Dashboard",
        "cells": [
            {"name": "chart1", "type": "barchart"},
            {"name": "kpi1", "type": "kpi"},
        ],
        "fields_used": ["OrderID", "Amount", "Region"],
    })
    cursor.execute(
        "INSERT INTO qlik_objects VALUES (?, ?, ?)",
        ("sheet01", "sheet", sheet_data),
    )

    measure_data = json.dumps({
        "title": "Total Sales",
        "expression": "Sum(Amount)",
        "label": "Total Sales Amount",
    })
    cursor.execute(
        "INSERT INTO qlik_objects VALUES (?, ?, ?)",
        ("measure01", "measure", measure_data),
    )

    dimension_data = json.dumps({
        "title": "Region",
        "field": "Region",
        "label": "Sales Region",
    })
    cursor.execute(
        "INSERT INTO qlik_objects VALUES (?, ?, ?)",
        ("dim01", "dimension", dimension_data),
    )

    # Insert load script
    cursor.execute(
        "INSERT INTO qlik_load_script VALUES (?)",
        ("LOAD OrderID, Amount, OrderDate, CustomerID FROM [lib://DataFiles/sales.csv];",),
    )

    conn.commit()
    conn.close()
    return qvf_path


def _create_empty_qvf(path: Path) -> Path:
    """Create an empty SQLite database with .qvf extension (no known tables)."""
    qvf_path = path / "empty.qvf"
    conn = sqlite3.connect(str(qvf_path))
    conn.commit()
    conn.close()
    return qvf_path


def _create_non_sqlite_qvf(path: Path) -> Path:
    """Create a file with .qvf extension that is not a valid SQLite database."""
    qvf_path = path / "garbage.qvf"
    qvf_path.write_bytes(b"This is not a SQLite database\x00\x01\x02")
    return qvf_path


# ---------------------------------------------------------------------------
# TestQvfParserContract
# ---------------------------------------------------------------------------

class TestQvfParserContract:
    """Verify the parser satisfies the BaseParser contract."""

    def test_extensions(self) -> None:
        parser = QvfParser()
        assert ".qvf" in parser.extensions

    def test_tool_name(self) -> None:
        parser = QvfParser()
        assert parser.tool == "Qlik Sense"

    def test_can_parse_qvf(self) -> None:
        parser = QvfParser()
        assert parser.can_parse(Path("app.qvf")) is True
        assert parser.can_parse(Path("app.QVF")) is True

    def test_cannot_parse_other(self) -> None:
        parser = QvfParser()
        assert parser.can_parse(Path("report.pbix")) is False
        assert parser.can_parse(Path("report.twb")) is False

    def test_check_dependencies(self) -> None:
        parser = QvfParser()
        available, _ = parser.check_dependencies()
        assert available is True


# ---------------------------------------------------------------------------
# TestQvfParserErrors
# ---------------------------------------------------------------------------

class TestQvfParserErrors:
    """Verify the parser handles bad inputs gracefully."""

    def test_missing_file(self, tmp_path: Path) -> None:
        parser = QvfParser()
        result = parser.parse(tmp_path / "nonexistent.qvf")
        assert len(result.errors) > 0

    def test_non_sqlite_file(self, tmp_path: Path) -> None:
        qvf_path = _create_non_sqlite_qvf(tmp_path)
        parser = QvfParser()
        result = parser.parse(qvf_path)
        assert len(result.errors) > 0

    def test_empty_sqlite_no_known_tables(self, tmp_path: Path) -> None:
        qvf_path = _create_empty_qvf(tmp_path)
        parser = QvfParser()
        result = parser.parse(qvf_path)
        # Empty DB with no known tables is not an error — just empty result
        assert result.errors == []
        assert result.datasources == []
        assert result.fields == []
        assert result.report_elements == []

    def test_parse_never_raises(self, tmp_path: Path) -> None:
        parser = QvfParser()
        # Should not raise for any of these
        parser.parse(tmp_path / "nonexistent.qvf")
        parser.parse(_create_non_sqlite_qvf(tmp_path))
        parser.parse(_create_empty_qvf(tmp_path))


# ---------------------------------------------------------------------------
# TestQvfParserSample
# ---------------------------------------------------------------------------

class TestQvfParserSample:
    """Verify extraction from a well-formed synthetic QVF fixture."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path: Path) -> None:
        qvf_path = _create_sample_qvf(tmp_path)
        self.parser = QvfParser()
        self.result = self.parser.parse(qvf_path)
        self.qvf_path = qvf_path

    # Basic result properties

    def test_parse_returns_no_errors(self) -> None:
        assert self.result.errors == [], f"Unexpected errors: {self.result.errors}"

    def test_source_file_set(self) -> None:
        assert self.result.source_file == str(self.qvf_path)

    def test_tool_name(self) -> None:
        assert self.result.tool_name == "Qlik Sense"

    def test_file_type(self) -> None:
        assert self.result.file_type == "qvf"

    # DataSources

    def test_extracts_datasources(self) -> None:
        assert len(self.result.datasources) == 2

    def test_datasource_names(self) -> None:
        names = {ds.name for ds in self.result.datasources}
        assert names == {"Sales", "Customers"}

    def test_datasource_connection_strings(self) -> None:
        sales_ds = next(ds for ds in self.result.datasources if ds.name == "Sales")
        assert "sales.csv" in sales_ds.connection_string

    def test_datasource_connection_type_csv(self) -> None:
        sales_ds = next(ds for ds in self.result.datasources if ds.name == "Sales")
        assert sales_ds.connection_type == "CSV"

    def test_datasource_connection_type_excel(self) -> None:
        customers_ds = next(ds for ds in self.result.datasources if ds.name == "Customers")
        assert customers_ds.connection_type == "Excel"

    # Fields from qlik_fields

    def test_extracts_fields(self) -> None:
        # 7 from qlik_fields + 1 measure + 1 dimension from qlik_objects
        qlik_fields = [f for f in self.result.fields if f.field_type not in ("measure", "dimension")]
        assert len(qlik_fields) == 7

    def test_field_names(self) -> None:
        field_names = [f.name for f in self.result.fields]
        for expected in ["OrderID", "Amount", "OrderDate", "CustomerID", "CustomerName", "Region"]:
            assert expected in field_names

    def test_field_data_types(self) -> None:
        amount_field = next(
            f for f in self.result.fields if f.name == "Amount" and f.data_type == "number"
        )
        assert amount_field.data_type == "number"

    def test_field_datasource(self) -> None:
        order_id = next(
            f for f in self.result.fields if f.name == "OrderID" and f.datasource == "Sales"
        )
        assert order_id.datasource == "Sales"

    def test_field_data_type_date(self) -> None:
        date_field = next(f for f in self.result.fields if f.name == "OrderDate")
        assert date_field.data_type == "date"

    # Measures from qlik_objects

    def test_extracts_measures_as_fields(self) -> None:
        measures = [f for f in self.result.fields if f.field_type == "measure" and f.role == "measure"]
        assert len(measures) >= 1

    def test_measure_name(self) -> None:
        measure = next(f for f in self.result.fields if f.name == "Total Sales")
        assert measure.name == "Total Sales"

    def test_measure_formula(self) -> None:
        measure = next(f for f in self.result.fields if f.name == "Total Sales")
        assert measure.formula == "Sum(Amount)"

    def test_measure_alias(self) -> None:
        measure = next(f for f in self.result.fields if f.name == "Total Sales")
        assert measure.alias == "Total Sales Amount"

    # Report elements (sheets)

    def test_extracts_report_elements(self) -> None:
        sheets = [e for e in self.result.report_elements if e.element_type == "sheet"]
        assert len(sheets) == 1

    def test_report_element_name(self) -> None:
        sheet = next(e for e in self.result.report_elements if e.element_type == "sheet")
        assert sheet.name == "Sales Dashboard"

    def test_report_element_fields_used(self) -> None:
        sheet = next(e for e in self.result.report_elements if e.element_type == "sheet")
        assert "Amount" in sheet.fields_used
        assert "Region" in sheet.fields_used

    # Load script in metadata

    def test_metadata_has_load_script(self) -> None:
        assert "load_script" in self.result.metadata
        assert "LOAD" in self.result.metadata["load_script"]
