"""Tests for the SSRS / Power BI Paginated Reports parser."""

from __future__ import annotations

from pathlib import Path

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
        assert len(self.result.datasources) == 3

    def test_first_datasource_name(self) -> None:
        names = [ds.name for ds in self.result.datasources]
        assert "SalesDB" in names

    def test_second_datasource_name(self) -> None:
        names = [ds.name for ds in self.result.datasources]
        assert "HRDataSource" in names

    def test_shared_datasource_name(self) -> None:
        names = [ds.name for ds in self.result.datasources]
        assert "SharedSource" in names

    def test_datasource_connection_type(self) -> None:
        ds_map = {ds.name: ds for ds in self.result.datasources}
        assert ds_map["SalesDB"].connection_type == "SQL"
        assert ds_map["HRDataSource"].connection_type == "OLEDB"

    def test_shared_datasource_connection_type(self) -> None:
        ds_map = {ds.name: ds for ds in self.result.datasources}
        assert ds_map["SharedSource"].connection_type == "SharedDataSource"

    def test_shared_datasource_connection_string(self) -> None:
        ds_map = {ds.name: ds for ds in self.result.datasources}
        assert ds_map["SharedSource"].connection_string == "/DataSources/CorporateDB"

    def test_datasource_connection_string(self) -> None:
        ds_map = {ds.name: ds for ds in self.result.datasources}
        assert "srv01" in ds_map["SalesDB"].connection_string
        assert "hr-srv" in ds_map["HRDataSource"].connection_string

    def test_datasource_database_extracted(self) -> None:
        ds_map = {ds.name: ds for ds in self.result.datasources}
        assert ds_map["SalesDB"].database == "Sales"
        assert ds_map["HRDataSource"].database == "HR"

    def test_datasource_alias(self) -> None:
        ds_map = {ds.name: ds for ds in self.result.datasources}
        assert ds_map["SalesDB"].alias == "SalesDB"

    def test_datasource_tables_from_sql(self) -> None:
        ds_map = {ds.name: ds for ds in self.result.datasources}
        assert "Orders" in ds_map["SalesDB"].tables


class TestSsrsParserFields:
    """Verify Field extraction from DataSet/Fields in the sample fixture."""

    def setup_method(self) -> None:
        self.parser = SsrsParser()
        self.result = self.parser.parse(SAMPLE_RDL)

    def test_field_count(self) -> None:
        # 4 regular + 2 calculated in SalesDataSet + 3 regular in EmployeeDataSet = 9
        assert len(self.result.fields) == 9

    def test_sales_field_names(self) -> None:
        names = [f.name for f in self.result.fields]
        for expected in ("OrderID", "CustomerName", "Amount", "OrderDate"):
            assert expected in names

    def test_employee_field_names(self) -> None:
        names = [f.name for f in self.result.fields]
        for expected in ("EmployeeID", "FullName", "Department"):
            assert expected in names

    def test_calculated_field_names(self) -> None:
        names = [f.name for f in self.result.fields]
        assert "TotalWithTax" in names
        assert "DisplayName" in names

    def test_regular_field_type(self) -> None:
        field_map = {f.name: f for f in self.result.fields}
        assert field_map["OrderID"].field_type == "regular"
        assert field_map["CustomerName"].field_type == "regular"

    def test_calculated_field_type(self) -> None:
        field_map = {f.name: f for f in self.result.fields}
        assert field_map["TotalWithTax"].field_type == "calculated"
        assert field_map["DisplayName"].field_type == "calculated"

    def test_calculated_field_formula(self) -> None:
        field_map = {f.name: f for f in self.result.fields}
        assert "Fields!Amount.Value" in field_map["TotalWithTax"].formula
        assert "1.1" in field_map["TotalWithTax"].formula

    def test_calculated_field_formula_status(self) -> None:
        field_map = {f.name: f for f in self.result.fields}
        assert field_map["TotalWithTax"].formula_status == "Success"

    def test_field_data_type_populated(self) -> None:
        field_map = {f.name: f for f in self.result.fields}
        assert field_map["OrderID"].data_type == "System.Int32"
        assert field_map["CustomerName"].data_type == "System.String"
        assert field_map["Amount"].data_type == "System.Decimal"
        assert field_map["OrderDate"].data_type == "System.DateTime"

    def test_field_alias_from_datafield(self) -> None:
        """DataField value should be used as alias when same as Name (empty)."""
        field_map = {f.name: f for f in self.result.fields}
        # When DataField equals Name, alias should be empty (no redundancy)
        assert field_map["OrderID"].alias == ""
        # Calculated fields have no DataField so no alias
        assert field_map["TotalWithTax"].alias == ""

    def test_field_role_inferred(self) -> None:
        field_map = {f.name: f for f in self.result.fields}
        # Numeric types → measure
        assert field_map["OrderID"].role == "measure"
        assert field_map["Amount"].role == "measure"
        # String types → dimension
        assert field_map["CustomerName"].role == "dimension"
        assert field_map["Department"].role == "dimension"

    def test_field_datasource_reference(self) -> None:
        field_map = {f.name: f for f in self.result.fields}
        assert field_map["OrderID"].datasource == "SalesDB"
        assert field_map["EmployeeID"].datasource == "HRDataSource"
        assert field_map["TotalWithTax"].datasource == "SalesDB"


class TestSsrsParserParameters:
    """Verify Parameter extraction from the sample fixture."""

    def setup_method(self) -> None:
        self.parser = SsrsParser()
        self.result = self.parser.parse(SAMPLE_RDL)

    def test_parameter_count(self) -> None:
        assert len(self.result.parameters) == 3

    def test_parameter_names(self) -> None:
        names = [p.name for p in self.result.parameters]
        assert "StartDate" in names
        assert "Region" in names
        assert "InternalFilter" in names

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

    def test_hidden_parameter_alias(self) -> None:
        param_map = {p.name: p for p in self.result.parameters}
        assert param_map["InternalFilter"].alias == "(Hidden)"

    def test_hidden_parameter_default_value(self) -> None:
        param_map = {p.name: p for p in self.result.parameters}
        assert param_map["InternalFilter"].default_value == "0"


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

    def test_tablix_fields_used(self) -> None:
        el_map = {el.name: el for el in self.result.report_elements}
        tablix = el_map["SalesTablix"]
        assert "OrderID" in tablix.fields_used
        assert "CustomerName" in tablix.fields_used
        assert "Amount" in tablix.fields_used
        assert "TotalWithTax" in tablix.fields_used

    def test_chart_fields_used(self) -> None:
        el_map = {el.name: el for el in self.result.report_elements}
        chart = el_map["SalesChart"]
        assert "OrderDate" in chart.fields_used
        assert "Amount" in chart.fields_used


class TestSsrsParserFilters:
    """Verify Filter extraction from DataSets and ReportItems."""

    def setup_method(self) -> None:
        self.parser = SsrsParser()
        self.result = self.parser.parse(SAMPLE_RDL)

    def test_filter_count(self) -> None:
        assert len(self.result.filters) >= 2

    def test_dataset_filter_extracted(self) -> None:
        ds_filters = [f for f in self.result.filters if f.scope.startswith("dataset:")]
        assert len(ds_filters) >= 1
        assert any(f.field == "Amount" for f in ds_filters)

    def test_dataset_filter_operator(self) -> None:
        ds_filters = [f for f in self.result.filters if f.scope.startswith("dataset:")]
        amount_filter = next(f for f in ds_filters if f.field == "Amount")
        assert amount_filter.filter_type == "GreaterThan"

    def test_tablix_filter_extracted(self) -> None:
        tablix_filters = [f for f in self.result.filters if f.scope.startswith("tablix:")]
        assert len(tablix_filters) >= 1
        assert any(f.field == "OrderDate" for f in tablix_filters)

    def test_tablix_filter_operator(self) -> None:
        tablix_filters = [f for f in self.result.filters if f.scope.startswith("tablix:")]
        date_filter = next(f for f in tablix_filters if f.field == "OrderDate")
        assert date_filter.filter_type == "GreaterThanOrEqual"


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
          <DataField>Id</DataField>
          <TypeName>System.Int32</TypeName>
        </Field>
        <Field Name="Name">
          <DataField>Name</DataField>
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
        assert result.datasources[0].database == "TestDB"

        assert len(result.fields) == 2
        field_names = [f.name for f in result.fields]
        assert "Id" in field_names
        assert "Name" in field_names

        # Verify role inference
        field_map = {f.name: f for f in result.fields}
        assert field_map["Id"].role == "measure"
        assert field_map["Name"].role == "dimension"

        assert len(result.parameters) == 1
        assert result.parameters[0].name == "Filter"

        assert len(result.report_elements) == 1
        assert result.report_elements[0].name == "ItemsTablix"


class TestSsrsParserCalculatedFields:
    """Verify calculated field extraction with Value expressions."""

    def test_calculated_field_with_expression(self, tmp_path: Path) -> None:
        rdl_content = """<?xml version="1.0" encoding="utf-8"?>
<Report>
  <DataSets>
    <DataSet Name="DS1">
      <Query>
        <DataSourceName>DS</DataSourceName>
        <CommandText>SELECT Price, Quantity FROM Products</CommandText>
      </Query>
      <Fields>
        <Field Name="Price">
          <DataField>Price</DataField>
          <TypeName>System.Decimal</TypeName>
        </Field>
        <Field Name="Quantity">
          <DataField>Quantity</DataField>
          <TypeName>System.Int32</TypeName>
        </Field>
        <Field Name="Total">
          <Value>=Fields!Price.Value * Fields!Quantity.Value</Value>
          <TypeName>System.Decimal</TypeName>
        </Field>
      </Fields>
    </DataSet>
  </DataSets>
</Report>
"""
        rdl_file = tmp_path / "calc.rdl"
        rdl_file.write_text(rdl_content, encoding="utf-8")

        parser = SsrsParser()
        result = parser.parse(rdl_file)

        assert result.errors == []
        assert len(result.fields) == 3

        field_map = {f.name: f for f in result.fields}

        # Regular fields
        assert field_map["Price"].field_type == "regular"
        assert field_map["Price"].formula == ""

        # Calculated field
        total = field_map["Total"]
        assert total.field_type == "calculated"
        assert "Fields!Price.Value" in total.formula
        assert "Fields!Quantity.Value" in total.formula
        assert total.formula_status == "Success"
        assert total.alias == ""  # No DataField for calculated fields


class TestSsrsParserSharedDataSource:
    """Verify shared datasource reference extraction."""

    def test_shared_datasource_reference(self, tmp_path: Path) -> None:
        rdl_content = """<?xml version="1.0" encoding="utf-8"?>
<Report>
  <DataSources>
    <DataSource Name="SharedDS">
      <DataSourceReference>/DataSources/MySharedDB</DataSourceReference>
    </DataSource>
  </DataSources>
</Report>
"""
        rdl_file = tmp_path / "shared.rdl"
        rdl_file.write_text(rdl_content, encoding="utf-8")

        parser = SsrsParser()
        result = parser.parse(rdl_file)

        assert result.errors == []
        assert len(result.datasources) == 1
        ds = result.datasources[0]
        assert ds.name == "SharedDS"
        assert ds.connection_type == "SharedDataSource"
        assert ds.connection_string == "/DataSources/MySharedDB"
