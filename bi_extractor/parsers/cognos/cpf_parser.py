"""Parser for IBM Cognos Framework Manager project files (.cpf).

CPF files are XML exports from Cognos Framework Manager containing metadata
model definitions: data sources, query subjects (tables), query items (fields),
relationships, parameters, and filters.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar
from xml.etree import ElementTree as ET

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
    Filter,
    Parameter,
    Relationship,
    ReportElement,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)


def _attr(element: ET.Element, *names: str) -> str:
    """Return the first matching attribute value."""
    for name in names:
        val = element.get(name, "")
        if val:
            return val.strip()
    return ""


def _child_text(element: ET.Element, tag: str) -> str:
    """Return stripped text of first matching child element."""
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _strip_ns(tag: str) -> str:
    """Strip XML namespace prefix from a tag name."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_all_local(root: ET.Element, local_name: str) -> list[ET.Element]:
    """Find all elements matching a local tag name, ignoring namespaces."""
    return [el for el in root.iter() if _strip_ns(el.tag) == local_name]


class CognosCpfParser(BaseParser):
    """Parser for IBM Cognos Framework Manager .cpf project files.

    CPF files are XML metadata model exports containing data source
    definitions, query subjects, query items, relationships, parameters,
    and filters used by the Cognos BI platform.
    """

    extensions: ClassVar[list[str]] = [".cpf"]
    tool: ClassVar[str] = "IBM Cognos Analytics"

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse an IBM Cognos Framework Manager .cpf file."""
        source = str(file_path)
        result = ExtractionResult(
            source_file=source,
            file_type=file_path.suffix.lower().lstrip("."),
            tool_name=self.tool,
        )

        try:
            tree = ET.parse(file_path)  # noqa: S314
            root = tree.getroot()
        except ET.ParseError as exc:
            msg = f"XML parse error in {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result
        except OSError as exc:
            msg = f"Cannot open {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        try:
            result.datasources = self._extract_datasources(root)
            result.fields = self._extract_fields(root)
            result.parameters = self._extract_parameters(root)
            result.relationships = self._extract_relationships(root)
            result.filters = self._extract_filters(root)
            result.report_elements = self._extract_report_elements(root)

            # Store project-level metadata
            project_name = _attr(root, "name", "projectName")
            if project_name:
                result.metadata["project_name"] = project_name

            description = _attr(root, "description")
            if description:
                result.metadata["description"] = description

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error parsing {source}: {exc}"
            logger.exception(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_datasources(self, root: ET.Element) -> list[DataSource]:
        """Extract data source definitions from the CPF project."""
        datasources: list[DataSource] = []

        for ds_el in _find_all_local(root, "dataSource"):
            name = _attr(ds_el, "name", "id")
            conn_type = _attr(ds_el, "connectionType", "type")
            conn_string = _attr(ds_el, "connectionString", "connectString")

            # Look for connection string in child text if not in attribute
            if not conn_string:
                conn_string = _child_text(ds_el, "connectionString")

            database = _attr(ds_el, "database", "catalog")
            schema = _attr(ds_el, "schema")

            # Collect table names from <schema><table> elements
            tables: list[str] = []
            seen_tables: set[str] = set()
            for schema_el in _find_all_local(ds_el, "schema"):
                if not schema:
                    schema = _attr(schema_el, "name")
                for tbl_el in list(schema_el):
                    if _strip_ns(tbl_el.tag) == "table":
                        tbl_name = _attr(tbl_el, "name")
                        if tbl_name and tbl_name not in seen_tables:
                            seen_tables.add(tbl_name)
                            tables.append(tbl_name)

            # Also check direct child <table> elements (flat layout, no schema wrapper)
            for tbl_el in list(ds_el):
                if _strip_ns(tbl_el.tag) == "table":
                    tbl_name = _attr(tbl_el, "name")
                    if tbl_name and tbl_name not in seen_tables:
                        seen_tables.add(tbl_name)
                        tables.append(tbl_name)

            datasources.append(
                DataSource(
                    name=name,
                    connection_type=conn_type,
                    connection_string=conn_string,
                    database=database,
                    schema=schema,
                    tables=tables,
                )
            )
            logger.debug("Cognos CPF: found data source '%s' (%s)", name, conn_type)

        return datasources

    def _extract_fields(self, root: ET.Element) -> list[Field]:
        """Extract query items from querySubject elements as fields."""
        fields: list[Field] = []

        for qs_el in _find_all_local(root, "querySubject"):
            qs_name = _attr(qs_el, "name", "id")

            for qi_el in list(qs_el):
                if _strip_ns(qi_el.tag) != "queryItem":
                    continue

                name = _attr(qi_el, "name", "id")
                if not name:
                    continue

                data_type = _attr(qi_el, "dataType", "type")
                expression = _attr(qi_el, "expression", "formula")
                if not expression:
                    expression = _child_text(qi_el, "expression")

                alias = _attr(qi_el, "alias", "displayName", "label")

                # Infer role from Cognos data types
                role = ""
                if data_type:
                    lower_dt = data_type.lower()
                    if lower_dt in (
                        "integer", "int32", "int64", "float", "double",
                        "decimal", "numeric", "money", "currency",
                    ):
                        role = "measure"
                    else:
                        role = "dimension"

                field_type = "calculated" if expression else "regular"
                fields.append(
                    Field(
                        name=name,
                        alias=alias,
                        data_type=data_type,
                        role=role,
                        field_type=field_type,
                        formula=expression,
                        original_formula=expression,
                        formula_status="Success" if expression else "",
                        datasource=qs_name,
                    )
                )
                logger.debug(
                    "Cognos CPF: found query item '%s' in '%s'", name, qs_name
                )

        return fields

    def _extract_parameters(self, root: ET.Element) -> list[Parameter]:
        """Extract parameter definitions from the project."""
        parameters: list[Parameter] = []

        for param_el in _find_all_local(root, "parameter"):
            name = _attr(param_el, "name", "id")
            if not name:
                continue

            data_type = _attr(param_el, "dataType", "type")
            default_value = _attr(param_el, "defaultValue", "default")
            prompt_text = _attr(param_el, "promptText", "displayName", "label")

            parameters.append(
                Parameter(
                    name=name,
                    data_type=data_type,
                    default_value=default_value,
                    prompt_text=prompt_text,
                )
            )
            logger.debug("Cognos CPF: found parameter '%s'", name)

        return parameters

    def _extract_relationships(self, root: ET.Element) -> list[Relationship]:
        """Extract relationship/join definitions between query subjects."""
        relationships: list[Relationship] = []

        for rel_el in _find_all_local(root, "relationship"):
            left = _attr(rel_el, "leftQuerySubject", "leftTable", "parent")
            right = _attr(rel_el, "rightQuerySubject", "rightTable", "child")
            join_type = _attr(rel_el, "joinType", "cardinality", "type")

            if not left or not right:
                continue

            # Collect join fields
            left_fields: list[str] = []
            right_fields: list[str] = []
            left_item = _attr(rel_el, "leftItem", "leftField")
            right_item = _attr(rel_el, "rightItem", "rightField")
            if left_item:
                left_fields.append(left_item)
            if right_item:
                right_fields.append(right_item)

            relationships.append(
                Relationship(
                    left_table=left,
                    right_table=right,
                    join_type=join_type,
                    left_fields=left_fields,
                    right_fields=right_fields,
                )
            )
            logger.debug(
                "Cognos CPF: found relationship '%s' -> '%s'", left, right
            )

        return relationships

    def _extract_filters(self, root: ET.Element) -> list[Filter]:
        """Extract filter definitions from the project."""
        filters: list[Filter] = []

        for filter_el in _find_all_local(root, "filter"):
            name = _attr(filter_el, "name", "id")
            if not name:
                continue

            expression = _attr(filter_el, "expression", "filterExpression")
            if not expression:
                expression = _child_text(filter_el, "expression")
            scope = _attr(filter_el, "scope", "usage")

            filters.append(
                Filter(
                    name=name,
                    filter_type="model",
                    scope=scope,
                    expression=expression,
                )
            )
            logger.debug("Cognos CPF: found filter '%s'", name)

        return filters

    def _extract_report_elements(self, root: ET.Element) -> list[ReportElement]:
        """Extract query subjects as report structural elements."""
        elements: list[ReportElement] = []

        for qs_el in _find_all_local(root, "querySubject"):
            name = _attr(qs_el, "name", "id")
            if not name:
                continue

            # Collect field names used in this query subject
            field_names: list[str] = []
            for qi_el in list(qs_el):
                if _strip_ns(qi_el.tag) == "queryItem":
                    qi_name = _attr(qi_el, "name")
                    if qi_name:
                        field_names.append(qi_name)

            elements.append(
                ReportElement(
                    name=name,
                    element_type="querySubject",
                    fields_used=field_names,
                )
            )
            logger.debug("Cognos CPF: found query subject element '%s'", name)

        return elements
