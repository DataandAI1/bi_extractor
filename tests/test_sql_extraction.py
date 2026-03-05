"""Tests for SQL extraction across all parsers and the sql_utils module."""

from __future__ import annotations

from pathlib import Path

import pytest

from bi_extractor.core.models import ExtractionResult, SQLQuery
from bi_extractor.core.sql_utils import contains_sql, extract_tables_from_sql, normalize_sql
from bi_extractor.output.csv_formatter import to_flat_rows

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ======================================================================
# sql_utils unit tests
# ======================================================================


class TestContainsSql:
    """Test the contains_sql detection function."""

    def test_select_from(self) -> None:
        assert contains_sql("SELECT id, name FROM users") is True

    def test_select_with_join(self) -> None:
        assert contains_sql("SELECT * FROM orders JOIN customers ON orders.cid = customers.id") is True

    def test_insert_into(self) -> None:
        assert contains_sql("INSERT INTO logs (msg) VALUES ('hello')") is True

    def test_update_set(self) -> None:
        assert contains_sql("UPDATE users SET name = 'foo' WHERE id = 1") is True

    def test_delete_from(self) -> None:
        assert contains_sql("DELETE FROM temp_table WHERE created < '2024-01-01'") is True

    def test_with_cte(self) -> None:
        assert contains_sql("WITH cte AS (SELECT 1) SELECT * FROM cte") is True

    def test_exec_procedure(self) -> None:
        assert contains_sql("EXEC sp_get_sales @year=2024") is True

    def test_create_table(self) -> None:
        assert contains_sql("CREATE TABLE foo (id INT, name VARCHAR(50))") is True

    def test_merge_into(self) -> None:
        assert contains_sql("MERGE INTO target USING source ON target.id = source.id") is True

    def test_empty_string(self) -> None:
        assert contains_sql("") is False

    def test_none_like(self) -> None:
        assert contains_sql("   ") is False

    def test_plain_text(self) -> None:
        assert contains_sql("This is just a regular description") is False

    def test_single_keyword_not_enough(self) -> None:
        # A bare "SELECT" without FROM shouldn't match
        assert contains_sql("SELECT") is False

    def test_expression_not_sql(self) -> None:
        assert contains_sql("[orders].[order_id]") is False

    def test_field_reference_not_sql(self) -> None:
        assert contains_sql("=Fields!Amount.Value * 1.1") is False


class TestExtractTablesFromSql:
    """Test table name extraction from SQL."""

    def test_simple_from(self) -> None:
        tables = extract_tables_from_sql("SELECT * FROM users")
        assert "users" in tables

    def test_multiple_tables(self) -> None:
        sql = "SELECT * FROM orders JOIN customers ON orders.cid = customers.id"
        tables = extract_tables_from_sql(sql)
        assert "orders" in tables
        assert "customers" in tables

    def test_schema_qualified(self) -> None:
        tables = extract_tables_from_sql("SELECT * FROM dbo.Orders")
        assert "Orders" in tables

    def test_bracketed_names(self) -> None:
        tables = extract_tables_from_sql("SELECT * FROM [dbo].[Orders]")
        assert "Orders" in tables

    def test_multiple_joins(self) -> None:
        sql = """
        SELECT o.id, c.name, p.title
        FROM orders o
        JOIN customers c ON o.cid = c.id
        LEFT JOIN products p ON o.pid = p.id
        """
        tables = extract_tables_from_sql(sql)
        assert len(tables) == 3
        assert "orders" in tables
        assert "customers" in tables
        assert "products" in tables

    def test_deduplication(self) -> None:
        sql = "SELECT * FROM users u JOIN users u2 ON u.id = u2.manager_id"
        tables = extract_tables_from_sql(sql)
        assert len(tables) == 1

    def test_empty_string(self) -> None:
        assert extract_tables_from_sql("") == []


class TestNormalizeSql:
    """Test SQL normalization."""

    def test_collapses_whitespace(self) -> None:
        result = normalize_sql("SELECT  *\n  FROM\n    users")
        assert result == "SELECT * FROM users"

    def test_trims(self) -> None:
        result = normalize_sql("  SELECT 1  ")
        assert result == "SELECT 1"

    def test_empty(self) -> None:
        assert normalize_sql("") == ""


# ======================================================================
# SQLQuery model tests
# ======================================================================


class TestSQLQueryModel:
    """Test the SQLQuery dataclass."""

    def test_basic_creation(self) -> None:
        sq = SQLQuery(name="test", sql_text="SELECT 1")
        assert sq.name == "test"
        assert sq.sql_text == "SELECT 1"
        assert sq.datasource == ""
        assert sq.dataset == ""
        assert sq.tables_referenced == []

    def test_full_creation(self) -> None:
        sq = SQLQuery(
            name="sales_query",
            sql_text="SELECT * FROM orders",
            datasource="SalesDB",
            dataset="SalesDataSet",
            tables_referenced=["orders"],
        )
        assert sq.datasource == "SalesDB"
        assert sq.tables_referenced == ["orders"]

    def test_extraction_result_has_sql_queries(self) -> None:
        result = ExtractionResult(
            source_file="test.rdl",
            file_type="rdl",
            tool_name="SSRS",
        )
        assert result.sql_queries == []


# ======================================================================
# SSRS Parser SQL extraction tests
# ======================================================================


class TestSsrsSqlExtraction:
    """Test SQL extraction from SSRS/RDL files."""

    def setup_method(self) -> None:
        from bi_extractor.parsers.microsoft.ssrs_parser import SsrsParser
        self.parser = SsrsParser()
        self.result = self.parser.parse(FIXTURES_DIR / "ssrs" / "sample.rdl")

    def test_no_errors(self) -> None:
        assert self.result.errors == []

    def test_sql_queries_extracted(self) -> None:
        assert len(self.result.sql_queries) > 0

    def test_sql_query_count(self) -> None:
        # sample.rdl has 2 datasets with SQL: SalesDataSet and EmployeeDataSet
        assert len(self.result.sql_queries) == 2

    def test_sql_query_names(self) -> None:
        names = [sq.name for sq in self.result.sql_queries]
        assert "SalesDataSet" in names
        assert "EmployeeDataSet" in names

    def test_sql_text_contains_select(self) -> None:
        for sq in self.result.sql_queries:
            assert "SELECT" in sq.sql_text

    def test_tables_referenced(self) -> None:
        sales_q = next(sq for sq in self.result.sql_queries if sq.name == "SalesDataSet")
        assert "Orders" in sales_q.tables_referenced

    def test_employee_tables(self) -> None:
        emp_q = next(sq for sq in self.result.sql_queries if sq.name == "EmployeeDataSet")
        assert "Employees" in emp_q.tables_referenced

    def test_datasource_populated(self) -> None:
        sales_q = next(sq for sq in self.result.sql_queries if sq.name == "SalesDataSet")
        assert sales_q.datasource == "SalesDB"

    def test_dataset_populated(self) -> None:
        sales_q = next(sq for sq in self.result.sql_queries if sq.name == "SalesDataSet")
        assert sales_q.dataset == "SalesDataSet"

    def test_metadata_queries_still_populated(self) -> None:
        """Backward compat: metadata['queries'] should still be populated."""
        assert "queries" in self.result.metadata
        assert len(self.result.metadata["queries"]) == 2


# ======================================================================
# Cognos CPF Parser SQL extraction tests
# ======================================================================


class TestCognosCpfSqlExtraction:
    """Test SQL extraction from Cognos CPF files."""

    def setup_method(self) -> None:
        from bi_extractor.parsers.cognos.cpf_parser import CognosCpfParser
        self.parser = CognosCpfParser()
        self.result = self.parser.parse(FIXTURES_DIR / "cognos" / "sample.cpf")

    def test_no_errors(self) -> None:
        assert self.result.errors == []

    def test_sql_queries_extracted(self) -> None:
        assert len(self.result.sql_queries) > 0

    def test_native_sql_found(self) -> None:
        names = [sq.name for sq in self.result.sql_queries]
        assert "OrdersSql" in names

    def test_sql_text_content(self) -> None:
        sq = next(sq for sq in self.result.sql_queries if sq.name == "OrdersSql")
        assert "SELECT" in sq.sql_text
        assert "orders" in sq.sql_text.lower()

    def test_tables_from_native_sql(self) -> None:
        sq = next(sq for sq in self.result.sql_queries if sq.name == "OrdersSql")
        table_names_lower = [t.lower() for t in sq.tables_referenced]
        assert "orders" in table_names_lower or "o" in table_names_lower


# ======================================================================
# BIRT Parser SQL extraction tests (using synthetic fixture)
# ======================================================================


class TestBirtSqlExtraction:
    """Test SQL extraction from BIRT rptdesign files."""

    def setup_method(self) -> None:
        from bi_extractor.parsers.eclipse.birt_parser import BirtParser
        self.parser = BirtParser()
        self.result = self.parser.parse(FIXTURES_DIR / "birt" / "sample.rptdesign")

    def test_no_errors(self) -> None:
        assert self.result.errors == []

    def test_sql_queries_count(self) -> None:
        assert len(self.result.sql_queries) >= 1

    def test_sql_text_has_select(self) -> None:
        sq = self.result.sql_queries[0]
        assert "SELECT" in sq.sql_text

    def test_tables_extracted(self) -> None:
        sq = self.result.sql_queries[0]
        assert "orders" in [t.lower() for t in sq.tables_referenced]

    def test_metadata_backward_compat(self) -> None:
        assert "sql_queries" in self.result.metadata


# ======================================================================
# JasperReports SQL extraction tests
# ======================================================================


class TestJasperSqlExtraction:
    """Test SQL extraction from JRXML files."""

    def setup_method(self) -> None:
        from bi_extractor.parsers.jasper.jrxml_parser import JrxmlParser
        self.parser = JrxmlParser()
        self.result = self.parser.parse(FIXTURES_DIR / "jasper" / "sample.jrxml")

    def test_no_errors(self) -> None:
        assert self.result.errors == []

    def test_sql_queries_count(self) -> None:
        assert len(self.result.sql_queries) == 1

    def test_sql_text_matches_metadata(self) -> None:
        sq = self.result.sql_queries[0]
        assert sq.sql_text == self.result.metadata["query"]

    def test_tables_extracted(self) -> None:
        sq = self.result.sql_queries[0]
        assert len(sq.tables_referenced) > 0

    def test_metadata_backward_compat(self) -> None:
        assert "query" in self.result.metadata


# ======================================================================
# Oracle XDO SQL extraction tests
# ======================================================================


class TestOracleXdoSqlExtraction:
    """Test SQL extraction from Oracle XDO files."""

    def setup_method(self) -> None:
        from bi_extractor.parsers.oracle.xdo_parser import OracleXdoParser
        self.parser = OracleXdoParser()
        self.result = self.parser.parse(FIXTURES_DIR / "oracle" / "sample.xdo")

    def test_no_errors(self) -> None:
        assert self.result.errors == []

    def test_sql_queries_count(self) -> None:
        assert len(self.result.sql_queries) >= 1

    def test_sql_text_has_select(self) -> None:
        sq = self.result.sql_queries[0]
        assert "SELECT" in sq.sql_text

    def test_tables_extracted(self) -> None:
        sq = self.result.sql_queries[0]
        assert len(sq.tables_referenced) > 0

    def test_metadata_backward_compat(self) -> None:
        assert "sql_queries" in self.result.metadata


# ======================================================================
# PBIX Parser SQL extraction tests (synthetic)
# ======================================================================


class TestPbixSqlExtraction:
    """Test SQL extraction from PBIX M expressions."""

    def test_native_query_in_m_expression(self, tmp_path: Path) -> None:
        import json
        import zipfile
        from bi_extractor.parsers.microsoft.pbix_parser import PbixParser

        model = {
            "model": {
                "tables": [
                    {
                        "name": "Sales",
                        "columns": [{"name": "id", "dataType": "int64"}],
                        "partitions": [
                            {
                                "source": {
                                    "type": "m",
                                    "expression": [
                                        'let',
                                        '    Source = Sql.Database("myserver", "mydb"),',
                                        '    Query = Value.NativeQuery(Source, "SELECT id, name, amount FROM dbo.sales_data JOIN dbo.regions ON sales_data.region_id = regions.id WHERE year = 2024")',
                                        'in',
                                        '    Query',
                                    ],
                                }
                            }
                        ],
                    }
                ],
                "dataSources": [],
            }
        }
        layout = {"sections": []}

        pbix_path = tmp_path / "test.pbix"
        with zipfile.ZipFile(pbix_path, "w") as zf:
            zf.writestr("DataModelSchema", json.dumps(model).encode("utf-8"))
            zf.writestr("Report/Layout", json.dumps(layout).encode("utf-8"))

        parser = PbixParser()
        result = parser.parse(pbix_path)

        assert result.errors == []
        assert len(result.sql_queries) >= 1

        sq = result.sql_queries[0]
        assert "SELECT" in sq.sql_text
        assert sq.dataset == "Sales"
        table_lower = [t.lower() for t in sq.tables_referenced]
        assert "sales_data" in table_lower
        assert "regions" in table_lower

    def test_no_sql_when_no_native_query(self, tmp_path: Path) -> None:
        import json
        import zipfile
        from bi_extractor.parsers.microsoft.pbix_parser import PbixParser

        model = {
            "model": {
                "tables": [
                    {
                        "name": "Simple",
                        "columns": [{"name": "id", "dataType": "int64"}],
                        "partitions": [
                            {
                                "source": {
                                    "type": "m",
                                    "expression": 'let Source = Sql.Database("srv", "db"), T = Source{[Schema="dbo",Item="mytable"]}[Data] in T',
                                }
                            }
                        ],
                    }
                ],
                "dataSources": [],
            }
        }
        layout = {"sections": []}

        pbix_path = tmp_path / "no_sql.pbix"
        with zipfile.ZipFile(pbix_path, "w") as zf:
            zf.writestr("DataModelSchema", json.dumps(model).encode("utf-8"))
            zf.writestr("Report/Layout", json.dumps(layout).encode("utf-8"))

        parser = PbixParser()
        result = parser.parse(pbix_path)

        assert result.errors == []
        assert len(result.sql_queries) == 0


# ======================================================================
# CSV Formatter SQL output tests
# ======================================================================


class TestCsvFormatterSqlOutput:
    """Test that CSV output includes SQL query columns."""

    def test_sql_columns_present_in_output(self) -> None:
        result = ExtractionResult(
            source_file="test.rdl",
            file_type="rdl",
            tool_name="SSRS",
        )
        result.sql_queries.append(
            SQLQuery(
                name="TestQuery",
                sql_text="SELECT id FROM users",
                tables_referenced=["users"],
            )
        )
        # Add a dummy field so we get a row
        from bi_extractor.core.models import Field
        result.fields.append(Field(name="id", datasource="ds1"))

        rows = to_flat_rows([result])
        assert len(rows) == 1
        row = rows[0]
        assert "SQL Query Count" in row
        assert row["SQL Query Count"] == "1"
        assert "SQL Queries" in row
        assert "TestQuery" in row["SQL Queries"]
        assert "SELECT id FROM users" in row["SQL Queries"]

    def test_no_sql_queries(self) -> None:
        result = ExtractionResult(
            source_file="test.rdl",
            file_type="rdl",
            tool_name="SSRS",
        )
        from bi_extractor.core.models import Field
        result.fields.append(Field(name="id", datasource="ds1"))

        rows = to_flat_rows([result])
        row = rows[0]
        assert row["SQL Query Count"] == "0"
        assert row["SQL Queries"] == ""

    def test_empty_result_row_has_sql_columns(self) -> None:
        result = ExtractionResult(
            source_file="empty.rdl",
            file_type="rdl",
            tool_name="SSRS",
        )
        rows = to_flat_rows([result])
        assert len(rows) == 1
        row = rows[0]
        assert "SQL Query Count" in row
        assert "SQL Queries" in row


# ======================================================================
# Synthetic parser test with SQL in Cognos CPF
# ======================================================================


class TestCognosCpfSyntheticSql:
    """Test Cognos CPF parser with synthetic SQL-containing fixtures."""

    def test_query_subject_with_native_sql(self, tmp_path: Path) -> None:
        from bi_extractor.parsers.cognos.cpf_parser import CognosCpfParser

        cpf_content = """<?xml version="1.0" encoding="UTF-8"?>
<project name="TestModel">
  <querySubjects>
    <querySubject name="SalesQuery">
      <sql>SELECT order_id, amount FROM dbo.orders WHERE status = 'active'</sql>
      <queryItem name="order_id" dataType="integer"/>
      <queryItem name="amount" dataType="decimal"/>
    </querySubject>
  </querySubjects>
</project>"""
        cpf_file = tmp_path / "test.cpf"
        cpf_file.write_text(cpf_content, encoding="utf-8")

        parser = CognosCpfParser()
        result = parser.parse(cpf_file)

        assert result.errors == []
        assert len(result.sql_queries) > 0

        # SQL is found via the <sql> element scan — may be named "sql" or "SalesQuery"
        sq = result.sql_queries[0]
        assert "SELECT" in sq.sql_text
        assert "orders" in [t.lower() for t in sq.tables_referenced]

    def test_standalone_sql_element(self, tmp_path: Path) -> None:
        from bi_extractor.parsers.cognos.cpf_parser import CognosCpfParser

        cpf_content = """<?xml version="1.0" encoding="UTF-8"?>
<project name="TestModel">
  <nativeSql name="RevenueQuery">SELECT SUM(amount) as revenue FROM sales JOIN regions ON sales.region_id = regions.id</nativeSql>
</project>"""
        cpf_file = tmp_path / "test_sql.cpf"
        cpf_file.write_text(cpf_content, encoding="utf-8")

        parser = CognosCpfParser()
        result = parser.parse(cpf_file)

        assert len(result.sql_queries) == 1
        sq = result.sql_queries[0]
        assert sq.name == "RevenueQuery"
        assert "SUM(amount)" in sq.sql_text
        table_lower = [t.lower() for t in sq.tables_referenced]
        assert "sales" in table_lower
        assert "regions" in table_lower

    def test_no_sql_when_none_present(self, tmp_path: Path) -> None:
        from bi_extractor.parsers.cognos.cpf_parser import CognosCpfParser

        cpf_content = """<?xml version="1.0" encoding="UTF-8"?>
<project name="NoSqlModel">
  <querySubjects>
    <querySubject name="Simple">
      <queryItem name="id" dataType="integer" expression="[table].[id]"/>
    </querySubject>
  </querySubjects>
</project>"""
        cpf_file = tmp_path / "nosql.cpf"
        cpf_file.write_text(cpf_content, encoding="utf-8")

        parser = CognosCpfParser()
        result = parser.parse(cpf_file)

        assert result.sql_queries == []
