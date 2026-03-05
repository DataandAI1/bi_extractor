"""Universal metadata model for BI report extraction.

Dataclasses that normalize metadata across all BI tools. All classes use
mutable dataclasses with slots=True for performance. The source_file field
lives ONLY on ExtractionResult — child entities inherit it from there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class DataSource:
    """A data connection within a report file."""

    name: str
    alias: str = ""
    connection_type: str = ""
    connection_string: str = ""
    database: str = ""
    schema: str = ""
    tables: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Field:
    """A column/field/measure within a data source."""

    name: str
    alias: str = ""
    data_type: str = ""
    role: str = ""
    field_type: str = ""
    formula: str = ""
    original_formula: str = ""
    formula_status: str = ""
    datasource: str = ""

    @property
    def dedup_key(self) -> tuple[str, str]:
        """Hashable key for deduplication."""
        return (self.name, self.datasource)


@dataclass(slots=True)
class Filter:
    """A filter/slicer applied to a report or visual."""

    name: str
    filter_type: str = ""
    scope: str = ""
    field: str = ""
    expression: str = ""


@dataclass(slots=True)
class ReportElement:
    """A structural element of a report (worksheet, page, section, etc.)."""

    name: str
    element_type: str = ""
    fields_used: list[str] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)

    @property
    def dedup_key(self) -> tuple[str, str]:
        """Hashable key for deduplication."""
        return (self.name, self.element_type)


@dataclass(slots=True)
class Parameter:
    """A report parameter."""

    name: str
    alias: str = ""
    data_type: str = ""
    default_value: str = ""
    allowed_values: list[str] = field(default_factory=list)
    prompt_text: str = ""


@dataclass(slots=True)
class Relationship:
    """A join/relationship between tables in a data model."""

    left_table: str
    right_table: str
    join_type: str = ""
    left_fields: list[str] = field(default_factory=list)
    right_fields: list[str] = field(default_factory=list)
    datasource: str = ""


@dataclass(slots=True)
class SQLQuery:
    """An embedded SQL query extracted from a report definition."""

    name: str
    sql_text: str
    datasource: str = ""
    dataset: str = ""
    tables_referenced: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ExtractionResult:
    """Complete extraction result for a single report file.

    This is the only place source_file lives. All child entities
    (DataSource, Field, etc.) are contained within and inherit the
    source file context from this parent.
    """

    source_file: str
    file_type: str
    tool_name: str
    datasources: list[DataSource] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    report_elements: list[ReportElement] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    sql_queries: list[SQLQuery] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def error_result(
        cls, source_file: str, file_type: str, tool_name: str, error: str
    ) -> ExtractionResult:
        """Create a result representing a failed extraction."""
        return cls(
            source_file=source_file,
            file_type=file_type,
            tool_name=tool_name,
            errors=[error],
        )
