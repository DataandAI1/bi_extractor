"""Tests for the universal metadata model."""

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
    Filter,
    Parameter,
    Relationship,
    ReportElement,
)


class TestDataSource:
    def test_create_minimal(self) -> None:
        ds = DataSource(name="test_ds")
        assert ds.name == "test_ds"
        assert ds.alias == ""
        assert ds.tables == []

    def test_create_full(self) -> None:
        ds = DataSource(
            name="sales_db",
            alias="Sales Database",
            connection_type="sqlserver",
            connection_string="Server=localhost;Database=sales",
            database="sales",
            schema="dbo",
            tables=["orders", "customers"],
        )
        assert ds.connection_type == "sqlserver"
        assert len(ds.tables) == 2

    def test_mutable(self) -> None:
        ds = DataSource(name="test")
        ds.tables.append("new_table")
        assert "new_table" in ds.tables


class TestField:
    def test_create_minimal(self) -> None:
        f = Field(name="order_id")
        assert f.name == "order_id"
        assert f.formula == ""
        assert f.formula_status == ""

    def test_dedup_key(self) -> None:
        f = Field(name="amount", datasource="sales")
        assert f.dedup_key == ("amount", "sales")

    def test_dedup_key_uniqueness(self) -> None:
        f1 = Field(name="amount", datasource="sales")
        f2 = Field(name="amount", datasource="marketing")
        assert f1.dedup_key != f2.dedup_key

    def test_mutable(self) -> None:
        f = Field(name="calc")
        f.formula = "SUM([Sales])"
        f.formula_status = "success"
        assert f.formula == "SUM([Sales])"


class TestFilter:
    def test_create(self) -> None:
        flt = Filter(
            name="year_filter",
            filter_type="include",
            scope="report",
            field="Year",
            expression="2024",
        )
        assert flt.filter_type == "include"
        assert flt.scope == "report"


class TestReportElement:
    def test_create(self) -> None:
        re = ReportElement(
            name="Sales Dashboard",
            element_type="worksheet",
            fields_used=["Sales", "Profit"],
        )
        assert re.element_type == "worksheet"
        assert len(re.fields_used) == 2

    def test_dedup_key(self) -> None:
        re = ReportElement(name="Sheet1", element_type="worksheet")
        assert re.dedup_key == ("Sheet1", "worksheet")

    def test_filters_list(self) -> None:
        flt = Filter(name="f1", filter_type="include")
        re = ReportElement(name="Sheet1", filters=[flt])
        assert len(re.filters) == 1
        assert re.filters[0].name == "f1"


class TestParameter:
    def test_create(self) -> None:
        p = Parameter(
            name="start_date",
            alias="Start Date",
            data_type="date",
            default_value="2024-01-01",
            prompt_text="Select start date",
        )
        assert p.data_type == "date"


class TestRelationship:
    def test_create(self) -> None:
        r = Relationship(
            left_table="orders",
            right_table="customers",
            join_type="inner",
            left_fields=["customer_id"],
            right_fields=["id"],
            datasource="sales_db",
        )
        assert r.join_type == "inner"
        assert r.left_fields == ["customer_id"]


class TestExtractionResult:
    def test_create_minimal(self) -> None:
        result = ExtractionResult(
            source_file="report.twb",
            file_type="twb",
            tool_name="Tableau",
        )
        assert result.source_file == "report.twb"
        assert result.datasources == []
        assert result.fields == []
        assert result.errors == []
        assert result.metadata == {}

    def test_error_result(self) -> None:
        result = ExtractionResult.error_result(
            source_file="bad.twb",
            file_type="twb",
            tool_name="Tableau",
            error="Failed to parse XML",
        )
        assert len(result.errors) == 1
        assert "Failed to parse" in result.errors[0]
        assert result.fields == []

    def test_mutable_accumulation(self) -> None:
        """Verify the multi-pass accumulation pattern works (no frozen)."""
        result = ExtractionResult(
            source_file="report.twb",
            file_type="twb",
            tool_name="Tableau",
        )
        # Pass 1: add datasources
        result.datasources.append(DataSource(name="ds1"))
        # Pass 2: add fields
        result.fields.append(Field(name="f1", datasource="ds1"))
        result.fields.append(Field(name="f2", datasource="ds1"))
        # Pass 3: add report elements
        result.report_elements.append(
            ReportElement(name="Sheet1", fields_used=["f1", "f2"])
        )
        assert len(result.datasources) == 1
        assert len(result.fields) == 2
        assert len(result.report_elements) == 1

    def test_field_deduplication(self) -> None:
        """Verify dedup_key can be used for set-based deduplication."""
        fields = [
            Field(name="Sales", datasource="ds1"),
            Field(name="Sales", datasource="ds1"),  # duplicate
            Field(name="Profit", datasource="ds1"),
        ]
        seen: set[tuple[str, str]] = set()
        unique: list[Field] = []
        for f in fields:
            if f.dedup_key not in seen:
                seen.add(f.dedup_key)
                unique.append(f)
        assert len(unique) == 2
