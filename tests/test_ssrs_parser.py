"""Tests for the SSRS / Power BI Paginated Reports parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from bi_extractor.parsers.microsoft.ssrs_parser import SsrsParser

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "ssrs"
SAMPLE_RDL = FIXTURES_DIR / "sample.rdl"


class TestSsrsParserContract:
    """Verify the parser satisfies the BaseParser contract."""

    def test_extensions(self) -> None:
        parser = SsrsParser()
        assert ".rdl" in parser.extensions
        assert ".rdlc" in parser.extensions

    def test_tool_name(self) -> None:
        parser = SsrsParser()
        assert parser.tool == "SSRS"

    def test_can_parse_rdl(self) -> None:
        parser = SsrsParser()
        assert parser.can_parse(Path("report.rdl")) is True
        assert parser.can_parse(Path("report.RDL")) is True

    def test_can_parse_rdlc(self) -> None:
        parser = SsrsParser()
        assert parser.can_parse(Path("report.rdlc")) is True

    def test_cannot_parse_other(self) -> None:
        parser = SsrsParser()
        assert parser.can_parse(Path("report.pbix")) is False
        assert parser.can_parse(Path("report.twb")) is False

    def test_check_dependencies(self) -> None:
        parser = SsrsParser()
        available, _ = parser.check_dependencies()
        assert available is True


class TestSsrsParserDataSources:
    """Verify DataSource extraction from the sample fixture."""

    def setup_method(self) -> None:
        self.parser = SsrsParser()
        self.result = self.parser.parse(SAMPLE_RDL)

    def test_no_errors(self) -> None:
        assert self.result.errors == [], f"Unexpected errors: {self.result.errors}"

    def test_datasource_count(self) -> None:
        assert len(self.result.datasources) == 2

    def test_first_datasource_name(self) -> None:
        names = [ds.name for ds in self.result.datasources]
        assert "SalesDB" in names

    def test_second_datasource_name(self) -> None:
        names = [ds.name for ds in self.result.datasources]
        assert "HRDataSource" in names

    def test_datasource_connection_type(self) -> None:
        ds_map = {ds.name: ds for ds in self.result.datasources}
        assert ds_map["SalesDB"].connection_type == "SQL"
        assert ds_map["HRDataSource"].connection_type == "OLEDB"

    def test_datasource_connection_string(self) -> None:
        ds_map = {ds.name: ds for ds in self.result.datasources}
        assert "srv01" in ds_map["SalesDB"].connection_string
        assert "hr-srv" in ds_map["HRDataSource"].connection_string


class TestSsrsParserFields:
    """Verify Field extraction from DataSet/Fields in the sample fixture."""

    def setup_method(self) -> None:
        self.parser = SsrsParser()
        self.result = self.parser.parse(SAMPLE_RDL)

    def test_field_count(self) -> None:
        # 4 fields in SalesDataSet + 3 fields in EmployeeDataSet = 7
        assert len(self.result.fields) == 7

    def test_sales_field_names(self) -> None:
        names = [f.name for f in self.result.fields]
        for expected in ("OrderID", "CustomerName", "Amount", "OrderDate"):
            assert expected in names

    def test_employee_field_names(self) -> None:
        names = [f.name for f in self.result.fields]
        for expected in ("EmployeeID", "FullName", "Department"):
            assert expected in names

    def test_field_type_is_regular(self) -> None:
        for f in self.result.fields:
            assert f.field_type == "regular"

    def test_field_data_type_populated(self) -> None:
        field_map = {f.name: f for f in self.result.fields}
        assert field_map["OrderID"].data_type == "System.Int32"
        assert field_map["CustomerName"].data_type == "System.String"
        assert field_map["Amount"].data_type == "System.Decimal"
        assert field_map["OrderDate"].data_type == "System.DateTime"

    def test_field_datasource_reference(self) -> None:
        field_map = {f.name: f for f in self.result.fields}
        assert field_map["OrderID"].datasource == "SalesDB"
        assert field_map["EmployeeID"].datasource == "HRDataSource"


class TestSsrsParserParameters:
    """Verify Parameter extraction from the sample fixture."""

    def setup_method(self) -> None:
        self.parser = SsrsParser()
        self.result = self.parser.parse(SAMPLE_RDL)

    def test_parameter_count(self) -> None:
        assert len(self.result.parameters) == 2

    def test_parameter_names(self) -> None:
        names = [p.name for p in self.result.parameters]
        assert "StartDate" in names
        assert "Region" in names

    def test_startdate_data_type(self) -> None:
        param_map = {p.name: p for p in self.result.parameters}
        assert param_map["StartDate"].data_type == "DateTime"

    def test_startdate_prompt(self) -> None:
        param_map = {p.name: p for p in self.result.parameters}
        assert param_map["StartDate"].prompt_text == "Start Date"

    def test_startdate_default_value(self) -> None:
        param_map = {p.name: p for p in self.result.parameters}
        assert param_map["StartDate"].default_value == "2024-01-01"

    def test_region_allowed_values(self) -> None:
        param_map = {p.name: p for p in self.result.parameters}
        assert set(param_map["Region"].allowed_values) == {"North", "South", "East", "West"}

    def test_region_prompt(self) -> None:
        param_map = {p.name: p for p in self.result.parameters}
        assert param_map["Region"].prompt_text == "Select Region"


class TestSsrsParserReportElements:
    """Verify ReportElement extraction from Body/ReportItems."""

    def setup_method(self) -> None:
        self.parser = SsrsParser()
        self.result = self.parser.parse(SAMPLE_RDL)

    def test_report_element_count(self) -> None:
        assert len(self.result.report_elements) == 3

    def test_tablix_extracted(self) -> None:
        el_map = {el.name: el for el in self.result.report_elements}
        assert "SalesTablix" in el_map
        assert el_map["SalesTablix"].element_type == "Tablix"

    def test_chart_extracted(self) -> None:
        el_map = {el.name: el for el in self.result.report_elements}
        assert "SalesChart" in el_map
        assert el_map["SalesChart"].element_type == "Chart"

    def test_textbox_extracted(self) -> None:
        el_map = {el.name: el for el in self.result.report_elements}
        assert "ReportTitle" in el_map
        assert el_map["ReportTitle"].element_type == "TextBox"


class TestSsrsParserMetadata:
    """Verify metadata (queries) stored in result.metadata."""

    def setup_method(self) -> None:
        self.parser = SsrsParser()
        self.result = self.parser.parse(SAMPLE_RDL)

    def test_queries_in_metadata(self) -> None:
        assert "queries" in self.result.metadata

    def test_query_content(self) -> None:
        queries = self.result.metadata["queries"]
        combined = " ".join(queries)
        assert "SELECT" in combined
        assert "OrderID" in combined


class TestSsrsParserErrorHandling:
    """Verify that parse() never raises and handles bad input gracefully."""

    def test_corrupt_xml_returns_error_not_exception(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "corrupt.rdl"
        bad_file.write_text("<<< this is not xml >>>", encoding="utf-8")
        parser = SsrsParser()
        result = parser.parse(bad_file)
        assert len(result.errors) > 0
        assert result.datasources == []
        assert result.fields == []

    def test_missing_file_returns_error_not_exception(self, tmp_path: Path) -> None:
        missing = tmp_path / "does_not_exist.rdl"
        parser = SsrsParser()
        result = parser.parse(missing)
        assert len(result.errors) > 0

    def test_empty_xml_no_crash(self, tmp_path: Path) -> None:
        empty_file = tmp_path / "empty.rdl"
        empty_file.write_text("<Report />", encoding="utf-8")
        parser = SsrsParser()
        result = parser.parse(empty_file)
        assert result.errors == []
        assert result.datasources == []
        assert result.fields == []
        assert result.parameters == []
        assert result.report_elements == []

    def test_result_source_file_set(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.rdl"
        bad_file.write_text("not xml", encoding="utf-8")
        parser = SsrsParser()
        result = parser.parse(bad_file)
        assert result.source_file == str(bad_file)

    def test_result_tool_name_set(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.rdl"
        bad_file.write_text("not xml", encoding="utf-8")
        parser = SsrsParser()
        result = parser.parse(bad_file)
        assert result.tool_name == "SSRS"


class TestSsrsParserNamespaceFree:
    """Verify the parser handles namespace-free RDL documents."""

    def test_namespace_free_rdl(self, tmp_path: Path) -> None:
        rdl_content = """<?xml version="1.0" encoding="utf-8"?>
<Report>
  <DataSources>
    <DataSource Name="MyDS">
      <ConnectionProperties>
        <DataProvider>SQL</DataProvider>
        <ConnectString>Data Source=localhost;Initial Catalog=TestDB</ConnectString>
      </ConnectionProperties>
    </DataSource>
  </DataSources>
  <DataSets>
    <DataSet Name="DS1">
      <Query>
        <DataSourceName>MyDS</DataSourceName>
        <CommandText>SELECT Id, Name FROM dbo.Items</CommandText>
      </Query>
      <Fields>
        <Field Name="Id">
          <TypeName>System.Int32</TypeName>
        </Field>
        <Field Name="Name">
          <TypeName>System.String</TypeName>
        </Field>
      </Fields>
    </DataSet>
  </DataSets>
  <ReportParameters>
    <ReportParameter Name="Filter">
      <DataType>String</DataType>
      <Prompt>Filter value</Prompt>
    </ReportParameter>
  </ReportParameters>
  <Body>
    <ReportItems>
      <Tablix Name="ItemsTablix" />
    </ReportItems>
  </Body>
</Report>
"""
        rdl_file = tmp_path / "no_ns.rdl"
        rdl_file.write_text(rdl_content, encoding="utf-8")

        parser = SsrsParser()
        result = parser.parse(rdl_file)

        assert result.errors == []
        assert len(result.datasources) == 1
        assert result.datasources[0].name == "MyDS"
        assert result.datasources[0].connection_type == "SQL"

        assert len(result.fields) == 2
        field_names = [f.name for f in result.fields]
        assert "Id" in field_names
        assert "Name" in field_names

        assert len(result.parameters) == 1
        assert result.parameters[0].name == "Filter"

        assert len(result.report_elements) == 1
        assert result.report_elements[0].name == "ItemsTablix"
