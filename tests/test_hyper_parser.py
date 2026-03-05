"""Tests for the Tableau Hyper extract parser."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bi_extractor.parsers.tableau.hyper_parser import HyperParser

# Check if tableauhyperapi is available
try:
    import tableauhyperapi  # noqa: F401
    HAS_HYPER_API = True
except ImportError:
    HAS_HYPER_API = False


@pytest.fixture
def parser() -> HyperParser:
    return HyperParser()


class TestHyperParserContract:
    """Verify that HyperParser satisfies the BaseParser contract."""

    def test_extensions(self, parser: HyperParser) -> None:
        assert parser.extensions == [".hyper"]

    def test_tool(self, parser: HyperParser) -> None:
        assert parser.tool == "Tableau"

    def test_can_parse_hyper_file(self, parser: HyperParser, tmp_path: Path) -> None:
        hyper_file = tmp_path / "data.hyper"
        hyper_file.write_bytes(b"")
        assert parser.can_parse(hyper_file) is True

    def test_cannot_parse_other_extension(self, parser: HyperParser, tmp_path: Path) -> None:
        twb_file = tmp_path / "data.twb"
        twb_file.write_bytes(b"")
        assert parser.can_parse(twb_file) is False

    def test_check_dependencies_when_available(self, parser: HyperParser) -> None:
        """When tableauhyperapi can be imported, check_dependencies returns True."""
        with patch.object(parser, "_import_hyper_api", return_value=MagicMock()):
            available, message = parser.check_dependencies()
        assert available is True
        assert "available" in message.lower()

    def test_check_dependencies_when_missing(self, parser: HyperParser) -> None:
        """When tableauhyperapi is absent, check_dependencies returns False with hint."""
        with patch.object(parser, "_import_hyper_api", side_effect=ImportError("no module")):
            available, message = parser.check_dependencies()
        assert available is False
        assert "pip install tableauhyperapi" in message


class TestHyperParserErrors:
    """Verify graceful error handling — parse() must never raise."""

    def test_missing_file_returns_error(self, parser: HyperParser, tmp_path: Path) -> None:
        non_existent = tmp_path / "ghost.hyper"
        # Provide a mock api so the dependency check passes
        mock_api = MagicMock()
        with patch.object(parser, "_import_hyper_api", return_value=mock_api):
            result = parser.parse(non_existent)
        assert len(result.errors) == 1
        assert "not found" in result.errors[0].lower() or "ghost.hyper" in result.errors[0]
        assert result.tool_name == "Tableau"
        assert result.file_type == "hyper"

    def test_missing_dependency_returns_error(self, parser: HyperParser, tmp_path: Path) -> None:
        hyper_file = tmp_path / "data.hyper"
        hyper_file.write_bytes(b"dummy")
        with patch.object(parser, "_import_hyper_api", side_effect=ImportError("no module")):
            result = parser.parse(hyper_file)
        assert len(result.errors) == 1
        assert "tableauhyperapi" in result.errors[0]
        assert result.tool_name == "Tableau"

    def test_corrupted_file_returns_error(self, parser: HyperParser, tmp_path: Path) -> None:
        """A HyperProcess error is caught and stored in errors."""
        hyper_file = tmp_path / "bad.hyper"
        hyper_file.write_bytes(b"not a real hyper file")

        mock_api = MagicMock()
        mock_api.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU = 0
        mock_api.HyperProcess.side_effect = RuntimeError("corrupt file")

        with patch.object(parser, "_import_hyper_api", return_value=mock_api):
            result = parser.parse(hyper_file)

        assert len(result.errors) == 1
        assert "corrupt file" in result.errors[0] or "bad.hyper" in result.errors[0]
        assert result.tool_name == "Tableau"


class TestHyperParserWithMock:
    """Test extraction logic using mocked tableauhyperapi."""

    def _setup_mock(self):
        """Create a comprehensive mock of tableauhyperapi objects."""
        mock_col1 = MagicMock()
        mock_col1.name = MagicMock()
        mock_col1.name.unescaped = "OrderID"
        mock_col1.type = MagicMock()
        mock_col1.type.tag = "BIG_INT"

        mock_col2 = MagicMock()
        mock_col2.name = MagicMock()
        mock_col2.name.unescaped = "Amount"
        mock_col2.type = MagicMock()
        mock_col2.type.tag = "DOUBLE"

        mock_col3 = MagicMock()
        mock_col3.name = MagicMock()
        mock_col3.name.unescaped = "OrderDate"
        mock_col3.type = MagicMock()
        mock_col3.type.tag = "DATE"

        mock_col4 = MagicMock()
        mock_col4.name = MagicMock()
        mock_col4.name.unescaped = "CustomerName"
        mock_col4.type = MagicMock()
        mock_col4.type.tag = "TEXT"

        mock_table_def = MagicMock()
        mock_table_def.columns = [mock_col1, mock_col2, mock_col3, mock_col4]

        mock_table_name = MagicMock()
        mock_table_name.schema_name = MagicMock()
        mock_table_name.schema_name.name = MagicMock()
        mock_table_name.schema_name.name.unescaped = "Extract"
        mock_table_name.name = MagicMock()
        mock_table_name.name.unescaped = "Extract"

        mock_schema = MagicMock()
        mock_schema.name = MagicMock()
        mock_schema.name.unescaped = "Extract"

        mock_catalog = MagicMock()
        mock_catalog.get_schema_names.return_value = [mock_schema]
        mock_catalog.get_table_names.return_value = [mock_table_name]
        mock_catalog.get_table_definition.return_value = mock_table_def

        mock_connection = MagicMock()
        mock_connection.catalog = mock_catalog
        mock_connection.__enter__ = MagicMock(return_value=mock_connection)
        mock_connection.__exit__ = MagicMock(return_value=False)

        mock_hyper = MagicMock()
        mock_hyper.endpoint = "localhost:12345"
        mock_hyper.__enter__ = MagicMock(return_value=mock_hyper)
        mock_hyper.__exit__ = MagicMock(return_value=False)

        return mock_hyper, mock_connection

    def _make_mock_api(self, mock_hyper: MagicMock, mock_conn: MagicMock) -> MagicMock:
        mock_module = MagicMock()
        mock_module.HyperProcess.return_value = mock_hyper
        mock_module.Connection.return_value = mock_conn
        mock_module.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU = 0
        return mock_module

    def test_extracts_fields(self, parser: HyperParser, tmp_path: Path) -> None:
        mock_hyper, mock_conn = self._setup_mock()
        hyper_file = tmp_path / "test.hyper"
        hyper_file.write_bytes(b"dummy")

        mock_module = self._make_mock_api(mock_hyper, mock_conn)
        with patch.object(parser, "_import_hyper_api", return_value=mock_module):
            result = parser.parse(hyper_file)

        assert len(result.fields) == 4
        assert result.errors == []

    def test_field_names(self, parser: HyperParser, tmp_path: Path) -> None:
        mock_hyper, mock_conn = self._setup_mock()
        hyper_file = tmp_path / "test.hyper"
        hyper_file.write_bytes(b"dummy")

        mock_module = self._make_mock_api(mock_hyper, mock_conn)
        with patch.object(parser, "_import_hyper_api", return_value=mock_module):
            result = parser.parse(hyper_file)

        names = [f.name for f in result.fields]
        assert "OrderID" in names
        assert "Amount" in names
        assert "OrderDate" in names
        assert "CustomerName" in names

    def test_field_data_types_normalized(self, parser: HyperParser, tmp_path: Path) -> None:
        mock_hyper, mock_conn = self._setup_mock()
        hyper_file = tmp_path / "test.hyper"
        hyper_file.write_bytes(b"dummy")

        mock_module = self._make_mock_api(mock_hyper, mock_conn)
        with patch.object(parser, "_import_hyper_api", return_value=mock_module):
            result = parser.parse(hyper_file)

        type_map = {f.name: f.data_type for f in result.fields}
        assert type_map["OrderID"] == "integer"
        assert type_map["Amount"] == "float"
        assert type_map["OrderDate"] == "date"
        assert type_map["CustomerName"] == "string"

    def test_field_datasource_set_to_schema_dot_table(
        self, parser: HyperParser, tmp_path: Path
    ) -> None:
        mock_hyper, mock_conn = self._setup_mock()
        hyper_file = tmp_path / "test.hyper"
        hyper_file.write_bytes(b"dummy")

        mock_module = self._make_mock_api(mock_hyper, mock_conn)
        with patch.object(parser, "_import_hyper_api", return_value=mock_module):
            result = parser.parse(hyper_file)

        for f in result.fields:
            assert f.datasource == "Extract.Extract"

    def test_extracts_one_datasource_per_schema(
        self, parser: HyperParser, tmp_path: Path
    ) -> None:
        mock_hyper, mock_conn = self._setup_mock()
        hyper_file = tmp_path / "test.hyper"
        hyper_file.write_bytes(b"dummy")

        mock_module = self._make_mock_api(mock_hyper, mock_conn)
        with patch.object(parser, "_import_hyper_api", return_value=mock_module):
            result = parser.parse(hyper_file)

        assert len(result.datasources) == 1
        ds = result.datasources[0]
        assert ds.name == "Extract"
        assert "Extract" in ds.tables

    def test_metadata_counts(self, parser: HyperParser, tmp_path: Path) -> None:
        mock_hyper, mock_conn = self._setup_mock()
        hyper_file = tmp_path / "test.hyper"
        hyper_file.write_bytes(b"dummy")

        mock_module = self._make_mock_api(mock_hyper, mock_conn)
        with patch.object(parser, "_import_hyper_api", return_value=mock_module):
            result = parser.parse(hyper_file)

        assert result.metadata["schema_count"] == 1
        assert result.metadata["table_count"] == 1
        assert result.metadata["column_count"] == 4

    def test_no_errors_on_valid_file(self, parser: HyperParser, tmp_path: Path) -> None:
        mock_hyper, mock_conn = self._setup_mock()
        hyper_file = tmp_path / "test.hyper"
        hyper_file.write_bytes(b"dummy")

        mock_module = self._make_mock_api(mock_hyper, mock_conn)
        with patch.object(parser, "_import_hyper_api", return_value=mock_module):
            result = parser.parse(hyper_file)

        assert result.errors == []

    def test_result_tool_name(self, parser: HyperParser, tmp_path: Path) -> None:
        mock_hyper, mock_conn = self._setup_mock()
        hyper_file = tmp_path / "test.hyper"
        hyper_file.write_bytes(b"dummy")

        mock_module = self._make_mock_api(mock_hyper, mock_conn)
        with patch.object(parser, "_import_hyper_api", return_value=mock_module):
            result = parser.parse(hyper_file)

        assert result.tool_name == "Tableau"
        assert result.file_type == "hyper"

    def test_multiple_schemas(self, parser: HyperParser, tmp_path: Path) -> None:
        """Multiple schemas each produce a separate DataSource."""
        # Schema A with one table, two columns
        mock_col_a1 = MagicMock()
        mock_col_a1.name.unescaped = "ID"
        mock_col_a1.type.tag = "INTEGER"

        mock_col_a2 = MagicMock()
        mock_col_a2.name.unescaped = "Name"
        mock_col_a2.type.tag = "TEXT"

        mock_table_def_a = MagicMock()
        mock_table_def_a.columns = [mock_col_a1, mock_col_a2]

        mock_table_a = MagicMock()
        mock_table_a.name.unescaped = "Customers"

        mock_schema_a = MagicMock()
        mock_schema_a.name.unescaped = "Public"

        # Schema B with one table, one column
        mock_col_b1 = MagicMock()
        mock_col_b1.name.unescaped = "Revenue"
        mock_col_b1.type.tag = "DOUBLE"

        mock_table_def_b = MagicMock()
        mock_table_def_b.columns = [mock_col_b1]

        mock_table_b = MagicMock()
        mock_table_b.name.unescaped = "Sales"

        mock_schema_b = MagicMock()
        mock_schema_b.name.unescaped = "Finance"

        mock_catalog = MagicMock()
        mock_catalog.get_schema_names.return_value = [mock_schema_a, mock_schema_b]

        def get_table_names(schema):
            if schema.name.unescaped == "Public":
                return [mock_table_a]
            return [mock_table_b]

        def get_table_definition(table):
            if table.name.unescaped == "Customers":
                return mock_table_def_a
            return mock_table_def_b

        mock_catalog.get_table_names.side_effect = get_table_names
        mock_catalog.get_table_definition.side_effect = get_table_definition

        mock_connection = MagicMock()
        mock_connection.catalog = mock_catalog
        mock_connection.__enter__ = MagicMock(return_value=mock_connection)
        mock_connection.__exit__ = MagicMock(return_value=False)

        mock_hyper = MagicMock()
        mock_hyper.endpoint = "localhost:12345"
        mock_hyper.__enter__ = MagicMock(return_value=mock_hyper)
        mock_hyper.__exit__ = MagicMock(return_value=False)

        mock_module = MagicMock()
        mock_module.HyperProcess.return_value = mock_hyper
        mock_module.Connection.return_value = mock_connection
        mock_module.Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU = 0

        hyper_file = tmp_path / "multi.hyper"
        hyper_file.write_bytes(b"dummy")

        with patch.object(parser, "_import_hyper_api", return_value=mock_module):
            result = parser.parse(hyper_file)

        assert len(result.datasources) == 2
        ds_names = {ds.name for ds in result.datasources}
        assert ds_names == {"Public", "Finance"}

        assert len(result.fields) == 3
        assert result.metadata["schema_count"] == 2
        assert result.metadata["table_count"] == 2
        assert result.metadata["column_count"] == 3
