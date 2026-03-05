"""Parser for SSRS / Power BI Paginated Reports (.rdl, .rdlc files).

RDL files are XML documents following Microsoft's Report Definition Language
schema. Multiple namespace versions are supported (2008, 2010, 2016) as well
as namespace-free documents.

Extracts:
  - Data sources (embedded and shared references) with database/schema parsing
  - Dataset fields with alias, data type, role, and calculated field detection
  - Embedded SQL queries with table extraction
  - Report parameters with defaults and allowed values
  - Report items (Tablix, Chart, TextBox, etc.) with field usage tracking
  - Filters at dataset and report-item levels
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
    Filter,
    Parameter,
    ReportElement,
    SQLQuery,
)
from bi_extractor.core.sql_utils import extract_tables_from_sql
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# All known RDL namespace URIs in chronological order.
_RDL_NAMESPACES: list[str] = [
    "http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition",
    "http://schemas.microsoft.com/sqlserver/reporting/2010/01/reportdefinition",
    "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition",
    "",  # namespace-free documents
]

# Regex to find =Fields!FieldName.Value references in RDL expressions
_FIELD_REF_RE = re.compile(r"Fields!(\w+)\.Value", re.IGNORECASE)

# Regex for connection string key=value parsing
_CONN_STR_RE = re.compile(r"([\w\s]+?)\s*=\s*([^;]*)")

# .NET numeric types that indicate a measure role
_NUMERIC_TYPES: set[str] = {
    "system.int16", "system.int32", "system.int64",
    "system.uint16", "system.uint32", "system.uint64",
    "system.single", "system.double", "system.decimal",
    "system.byte", "system.sbyte", "system.float",
    "system.money", "system.smallmoney",
    "system.numerics.biginteger",
}

# .NET date/time types
_DATETIME_TYPES: set[str] = {
    "system.datetime", "system.datetimeoffset",
    "system.timespan",
}


def _ns(tag: str, namespace: str) -> str:
    """Return a Clark-notation tag string for the given namespace."""
    if namespace:
        return f"{{{namespace}}}{tag}"
    return tag


def _detect_namespace(root: ET.Element) -> str:
    """Detect which RDL namespace the document uses."""
    tag = root.tag
    if tag.startswith("{"):
        end = tag.index("}")
        return tag[1:end]
    return ""


def _find_text(element: ET.Element, path: str, ns: str) -> str:
    """Return the text of the first matching child, or empty string."""
    parts = path.split("/")
    current: list[ET.Element] = [element]
    for part in parts:
        next_level: list[ET.Element] = []
        tag = _ns(part, ns)
        for el in current:
            next_level.extend(el.findall(tag))
        current = next_level
        if not current:
            return ""
    if current:
        return (current[0].text or "").strip()
    return ""


def _parse_connection_string(conn_str: str) -> dict[str, str]:
    """Parse a semicolon-delimited connection string into a dict."""
    result: dict[str, str] = {}
    for match in _CONN_STR_RE.finditer(conn_str):
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        result[key] = value
    return result


def _infer_role(data_type: str) -> str:
    """Infer dimension/measure role from .NET type name."""
    if not data_type:
        return ""
    lower = data_type.lower()
    if lower in _NUMERIC_TYPES:
        return "measure"
    return "dimension"




def _collect_field_refs(element: ET.Element) -> set[str]:
    """Recursively collect all Fields!Name.Value references from an element tree."""
    refs: set[str] = set()
    # Check all text content and attribute values in the subtree
    for el in element.iter():
        # Check element text
        if el.text:
            refs.update(_FIELD_REF_RE.findall(el.text))
        # Check tail text
        if el.tail:
            refs.update(_FIELD_REF_RE.findall(el.tail))
        # Check attribute values (expressions can be in attributes)
        for attr_val in el.attrib.values():
            refs.update(_FIELD_REF_RE.findall(attr_val))
    return refs


class SsrsParser(BaseParser):
    """Parse SSRS / Power BI Paginated Report files (.rdl, .rdlc).

    Extracts data sources, dataset fields, report parameters, report items,
    filters, and field usage from Report Definition Language XML.
    """

    extensions: list[str] = [".rdl", ".rdlc"]
    tool: str = "SSRS"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a single RDL/RDLC file.

        Never raises. Returns an ExtractionResult with errors populated on
        failure.
        """
        file_str = str(file_path)
        file_type = file_path.suffix.lstrip(".").lower()

        result = ExtractionResult(
            source_file=file_str,
            file_type=file_type,
            tool_name=self.tool,
        )

        try:
            tree = ET.parse(file_path)  # noqa: S314 — stdlib only, no network
            root = tree.getroot()
        except ET.ParseError as exc:
            msg = f"XML parse error in {file_str}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result
        except OSError as exc:
            msg = f"Cannot read {file_str}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        ns = _detect_namespace(root)
        logger.debug("Detected RDL namespace %r for %s", ns, file_str)

        try:
            # Build dataset→datasource mapping for field references
            dataset_ds_map: dict[str, str] = {}
            self._extract_datasources(root, ns, result)
            self._extract_datasets(root, ns, result, dataset_ds_map)
            self._extract_parameters(root, ns, result)
            self._extract_report_items(root, ns, result)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error while extracting metadata from {file_str}: {exc}"
            logger.exception(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # Private extraction helpers
    # ------------------------------------------------------------------

    def _extract_datasources(
        self, root: ET.Element, ns: str, result: ExtractionResult
    ) -> None:
        """Extract DataSource elements from //DataSources/DataSource.

        Handles both embedded connection properties and shared datasource
        references. Parses database and schema from connection strings.
        """
        datasources_el = root.find(_ns("DataSources", ns))
        if datasources_el is None:
            logger.debug("No <DataSources> element found.")
            return

        for ds_el in datasources_el.findall(_ns("DataSource", ns)):
            name = ds_el.get("Name", "").strip()
            if not name:
                continue

            connection_type = ""
            connection_string = ""
            database = ""
            schema = ""

            # Check for embedded ConnectionProperties
            conn_props = ds_el.find(_ns("ConnectionProperties", ns))
            if conn_props is not None:
                provider_el = conn_props.find(_ns("DataProvider", ns))
                if provider_el is not None:
                    connection_type = (provider_el.text or "").strip()

                connect_el = conn_props.find(_ns("ConnectString", ns))
                if connect_el is not None:
                    connection_string = (connect_el.text or "").strip()

            # Check for shared datasource reference
            ds_ref_el = ds_el.find(_ns("DataSourceReference", ns))
            if ds_ref_el is not None:
                ref_path = (ds_ref_el.text or "").strip()
                if ref_path:
                    connection_type = connection_type or "SharedDataSource"
                    connection_string = connection_string or ref_path

            # Parse database and schema from connection string
            if connection_string:
                conn_parts = _parse_connection_string(connection_string)
                database = conn_parts.get("initial catalog", "")
                if not database:
                    database = conn_parts.get("database", "")
                schema = conn_parts.get("schema", "")
                # Try to get server as alias
                server = conn_parts.get("data source", "")
                if not server:
                    server = conn_parts.get("server", "")

            result.datasources.append(
                DataSource(
                    name=name,
                    alias=name,
                    connection_type=connection_type,
                    connection_string=connection_string,
                    database=database,
                    schema=schema,
                )
            )
            logger.debug(
                "Found DataSource: %s (type=%s, db=%s)", name, connection_type, database
            )

    def _extract_datasets(
        self,
        root: ET.Element,
        ns: str,
        result: ExtractionResult,
        dataset_ds_map: dict[str, str],
    ) -> None:
        """Extract Fields and CommandText from //DataSets/DataSet elements.

        Populates dataset_ds_map with DataSet Name → DataSource Name mappings.
        Extracts field alias from DataField, detects calculated fields via
        Value expressions, infers role from data type, and extracts dataset
        filters. Also extracts table names from SQL queries.
        """
        datasets_el = root.find(_ns("DataSets", ns))
        if datasets_el is None:
            logger.debug("No <DataSets> element found.")
            return

        queries: dict[str, tuple[str, list[str]]] = {}

        for dataset_el in datasets_el.findall(_ns("DataSet", ns)):
            dataset_name = dataset_el.get("Name", "").strip()

            # Resolve the data source name for this dataset.
            datasource_ref = _find_text(dataset_el, "Query/DataSourceName", ns)
            if dataset_name:
                dataset_ds_map[dataset_name] = datasource_ref

            # Extract CommandText.
            command_text = _find_text(dataset_el, "Query/CommandText", ns)
            if command_text:
                # Extract tables once and cache with the SQL text
                tables = extract_tables_from_sql(command_text)
                queries[dataset_name] = (command_text, tables)

                # Add tables to the datasource
                if tables:
                    for ds in result.datasources:
                        if ds.name == datasource_ref:
                            for table in tables:
                                if table not in ds.tables:
                                    ds.tables.append(table)
                            break

            # Extract Fields.
            fields_el = dataset_el.find(_ns("Fields", ns))
            if fields_el is None:
                continue

            for field_el in fields_el.findall(_ns("Field", ns)):
                field_name = field_el.get("Name", "").strip()
                if not field_name:
                    continue

                # DataField = actual database column name (alias for display name)
                data_field_el = field_el.find(_ns("DataField", ns))
                data_field = (
                    (data_field_el.text or "").strip()
                    if data_field_el is not None
                    else ""
                )

                # Value = calculated expression (=Fields!X.Value + Fields!Y.Value)
                value_el = field_el.find(_ns("Value", ns))
                value_expr = (
                    (value_el.text or "").strip() if value_el is not None else ""
                )

                # TypeName = .NET data type
                type_el = field_el.find(_ns("TypeName", ns))
                data_type = (
                    (type_el.text or "").strip() if type_el is not None else ""
                )

                # Determine field type and formula
                if value_expr and not data_field:
                    # Calculated field — has Value expression but no DataField
                    field_type = "calculated"
                    formula = value_expr
                    formula_status = "Success"
                    alias = ""
                elif data_field:
                    # Regular database field
                    field_type = "regular"
                    formula = ""
                    formula_status = ""
                    # Alias is the DataField (actual DB column) when different from Name
                    alias = data_field if data_field != field_name else ""
                else:
                    field_type = "regular"
                    formula = ""
                    formula_status = ""
                    alias = ""

                # Infer role from data type
                role = _infer_role(data_type)

                result.fields.append(
                    Field(
                        name=field_name,
                        alias=alias,
                        data_type=data_type,
                        role=role,
                        field_type=field_type,
                        formula=formula,
                        original_formula=formula,
                        formula_status=formula_status,
                        datasource=datasource_ref,
                    )
                )
                logger.debug(
                    "Found Field: %s (alias=%s, type=%s, role=%s, field_type=%s, ds=%s)",
                    field_name,
                    alias,
                    data_type,
                    role,
                    field_type,
                    datasource_ref,
                )

            # Extract dataset-level filters
            self._extract_filters_from_element(
                dataset_el, ns, result, scope=f"dataset:{dataset_name}"
            )

        if queries:
            result.metadata["queries"] = [
                f"{name}: {sql}" for name, (sql, _tables) in queries.items()
            ]
            for ds_name, (sql_text, tables) in queries.items():
                datasource_ref = dataset_ds_map.get(ds_name, "")
                result.sql_queries.append(
                    SQLQuery(
                        name=ds_name,
                        sql_text=sql_text,
                        datasource=datasource_ref,
                        dataset=ds_name,
                        tables_referenced=tables,
                    )
                )

    def _extract_parameters(
        self, root: ET.Element, ns: str, result: ExtractionResult
    ) -> None:
        """Extract ReportParameter elements from //ReportParameters."""
        params_el = root.find(_ns("ReportParameters", ns))
        if params_el is None:
            logger.debug("No <ReportParameters> element found.")
            return

        for param_el in params_el.findall(_ns("ReportParameter", ns)):
            name = param_el.get("Name", "").strip()
            if not name:
                continue

            data_type_el = param_el.find(_ns("DataType", ns))
            data_type = (data_type_el.text or "").strip() if data_type_el is not None else ""

            prompt_el = param_el.find(_ns("Prompt", ns))
            prompt_text = (prompt_el.text or "").strip() if prompt_el is not None else ""

            # Default value — may be under DefaultValue/Values/Value.
            default_value = _find_text(param_el, "DefaultValue/Values/Value", ns)

            # Allowed values — ValidValues/ParameterValues/ParameterValue/Value.
            allowed: list[str] = []
            valid_vals_el = param_el.find(_ns("ValidValues", ns))
            if valid_vals_el is not None:
                # Try ParameterValues/ParameterValue path first (some RDL versions)
                pv_container = valid_vals_el.find(_ns("ParameterValues", ns))
                if pv_container is not None:
                    pv_els = pv_container.findall(_ns("ParameterValue", ns))
                else:
                    # Direct ParameterValue children
                    pv_els = valid_vals_el.findall(_ns("ParameterValue", ns))

                for pv_el in pv_els:
                    val_el = pv_el.find(_ns("Value", ns))
                    if val_el is not None and val_el.text:
                        allowed.append(val_el.text.strip())

            # Hidden flag
            hidden_el = param_el.find(_ns("Hidden", ns))
            is_hidden = (
                (hidden_el.text or "").strip().lower() == "true"
                if hidden_el is not None
                else False
            )

            # MultiValue flag
            multi_el = param_el.find(_ns("MultiValue", ns))
            is_multi = (
                (multi_el.text or "").strip().lower() == "true"
                if multi_el is not None
                else False
            )

            alias = ""
            if is_hidden:
                alias = "(Hidden)"
            elif is_multi:
                alias = "(MultiValue)"

            result.parameters.append(
                Parameter(
                    name=name,
                    alias=alias,
                    data_type=data_type,
                    default_value=default_value,
                    allowed_values=allowed,
                    prompt_text=prompt_text,
                )
            )
            logger.debug("Found Parameter: %s (type=%s)", name, data_type)

    def _extract_report_items(
        self,
        root: ET.Element,
        ns: str,
        result: ExtractionResult,
    ) -> None:
        """Extract report items from Body with field usage tracking and filters.

        Traverses Tablix, Chart, and other report items to find:
        - DataSetName references
        - Fields!Name.Value expression references
        - Filters at the report-item level
        """
        body_el = root.find(_ns("Body", ns))
        if body_el is None:
            logger.debug("No <Body> element found.")
            return

        report_items_el = body_el.find(_ns("ReportItems", ns))
        if report_items_el is None:
            logger.debug("No <ReportItems> under Body.")
            return

        for item_el in report_items_el:
            # The local tag name is the element type (Tablix, Chart, TextBox, …).
            tag = item_el.tag
            if tag.startswith("{"):
                tag = tag.split("}", 1)[1]

            name = item_el.get("Name", tag).strip()

            # Collect field references from expressions in this item
            field_refs = _collect_field_refs(item_el)
            fields_used = sorted(field_refs)

            # Extract filters at the report-item level
            self._extract_filters_from_element(
                item_el, ns, result, scope=f"{tag.lower()}:{name}"
            )

            result.report_elements.append(
                ReportElement(
                    name=name,
                    element_type=tag,
                    fields_used=fields_used,
                )
            )
            logger.debug(
                "Found ReportElement: %s (%s, fields=%d)",
                name,
                tag,
                len(fields_used),
            )

    def _extract_filters_from_element(
        self,
        parent_el: ET.Element,
        ns: str,
        result: ExtractionResult,
        scope: str,
    ) -> None:
        """Extract Filter elements from a Filters container within parent_el.

        RDL filters appear under DataSet, Tablix, TablixGroup, Chart, etc.
        Each Filter has FilterExpression, Operator, and FilterValues.
        """
        filters_el = parent_el.find(_ns("Filters", ns))
        if filters_el is None:
            return

        for filter_el in filters_el.findall(_ns("Filter", ns)):
            # FilterExpression — usually =Fields!Name.Value
            filter_expr = _find_text(filter_el, "FilterExpression", ns)
            operator = _find_text(filter_el, "Operator", ns)

            # FilterValues/FilterValue — the comparison value(s)
            filter_values: list[str] = []
            fv_container = filter_el.find(_ns("FilterValues", ns))
            if fv_container is not None:
                for fv_el in fv_container.findall(_ns("FilterValue", ns)):
                    if fv_el.text:
                        filter_values.append(fv_el.text.strip())

            # Extract field name from expression
            field_name = ""
            if filter_expr:
                field_match = _FIELD_REF_RE.search(filter_expr)
                if field_match:
                    field_name = field_match.group(1)

            # Build expression string
            value_str = ", ".join(filter_values) if filter_values else ""
            expression = f"{filter_expr} {operator} {value_str}".strip()

            result.filters.append(
                Filter(
                    name=field_name or filter_expr or "filter",
                    filter_type=operator,
                    scope=scope,
                    field=field_name,
                    expression=expression,
                )
            )
            logger.debug(
                "Found Filter: %s (op=%s, scope=%s)", field_name, operator, scope
            )
