"""Parser for Power BI Desktop report files (.pbix).

PBIX files are ZIP archives containing a JSON-based data model schema
and report layout definition with pages, visuals, filters, and data connections.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, ClassVar

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
    Filter,
    Relationship,
    ReportElement,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# Regex to extract Sql.Database("server", "db") style M expressions
_SQL_DATABASE_RE = re.compile(
    r'Sql\.Database\s*\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
    re.IGNORECASE,
)

# Mapping for crossFilteringBehavior integer values
_CROSS_FILTER_MAP: dict[int, str] = {
    1: "oneDirection",
    2: "bothDirections",
}

# Regex for connection string key=value parsing
_CONN_STR_RE = re.compile(r"([\w\s]+?)\s*=\s*([^;]*)")

# Power BI data types that indicate a measure role
_NUMERIC_DATATYPES: set[str] = {
    "int64", "double", "decimal", "currency", "percentage",
}


def _parse_connection_string(conn_str: str) -> dict[str, str]:
    """Parse a semicolon-delimited connection string into a dict."""
    result: dict[str, str] = {}
    for match in _CONN_STR_RE.finditer(conn_str):
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        result[key] = value
    return result


def _infer_role(data_type: str) -> str:
    """Infer dimension/measure role from Power BI data type."""
    if not data_type:
        return ""
    if data_type.lower() in _NUMERIC_DATATYPES:
        return "measure"
    return "dimension"


class PbixParser(BaseParser):
    """Parser for Power BI Desktop .pbix report files.

    PBIX files are ZIP archives containing a JSON-based data model schema
    (DataModelSchema) and a report layout definition (Report/Layout) with
    pages, visuals, filters, and data connections.
    """

    extensions: ClassVar[list[str]] = [".pbix"]
    tool: ClassVar[str] = "Power BI"

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a Power BI Desktop .pbix file."""
        source = str(file_path)
        result = ExtractionResult(
            source_file=source,
            file_type=file_path.suffix.lower().lstrip("."),
            tool_name=self.tool,
        )

        # Attempt to open as ZIP
        try:
            zf = zipfile.ZipFile(file_path, "r")
        except FileNotFoundError as exc:
            msg = f"Cannot open {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result
        except zipfile.BadZipFile as exc:
            msg = f"Invalid ZIP/PBIX file {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result
        except OSError as exc:
            msg = f"Cannot open {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        with zf:
            model = self._read_json_entry(zf, "DataModelSchema", source, result)
            layout = self._read_json_entry(zf, "Report/Layout", source, result)

        try:
            if model is not None:
                # Real PBIX files use TMSL format where tables/relationships/
                # dataSources are nested under a "model" key.  The synthetic
                # test fixtures put them at the top level, so accept both.
                inner = model.get("model", model)

                result.datasources = self._extract_datasources(inner)
                result.fields = self._extract_fields(inner)
                result.relationships = self._extract_relationships(inner)

                # Model name lives at the top level in TMSL
                model_name = model.get("name")
                if model_name:
                    result.metadata["model_name"] = model_name

            if layout is not None:
                result.report_elements = self._extract_report_elements(layout)
                result.filters = self._extract_filters(layout)

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error parsing {source}: {exc}"
            logger.exception(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # ZIP helpers
    # ------------------------------------------------------------------

    def _read_json_entry(
        self,
        zf: zipfile.ZipFile,
        entry_name: str,
        source: str,
        result: ExtractionResult,
    ) -> dict[str, Any] | None:
        """Read and JSON-parse a named entry from the ZIP. Returns None on failure."""
        names = zf.namelist()
        if entry_name not in names:
            logger.warning("PBIX: '%s' not found in %s", entry_name, source)
            return None
        try:
            raw = zf.read(entry_name)
            
            # Power BI sometimes writes UTF-16 LE with BOM; detect by BOM bytes
            if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
                text = raw.decode("utf-16").lstrip("\ufeff")
            elif len(raw) >= 2 and raw[0] in (b"{"[0], b"["[0]) and raw[1] == 0:
                # UTF-16LE without BOM (common in Report/Layout)
                text = raw.decode("utf-16le")
            else:
                # Standard UTF-8 (with or without BOM)
                text = raw.decode("utf-8-sig")
                
            # Clean up trailing nulls which Power BI sometimes appends
            text = text.strip("\x00")
            
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # Fallback: if interpreted as UTF-8 but contains nulls, it might be UTF-16LE
                if "\x00" in text:
                    text = raw.decode("utf-16le").strip("\x00")
                    parsed = json.loads(text)
                else:
                    raise
                    
            return parsed  # type: ignore[no-any-return]
        except json.JSONDecodeError as exc:
            msg = f"JSON parse error in {entry_name} ({source}): {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return None
        except Exception as exc:  # noqa: BLE001
            msg = f"Error reading {entry_name} from {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return None

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_datasources(self, model: dict[str, Any]) -> list[DataSource]:
        """Extract data source definitions from the model."""
        datasources: list[DataSource] = []
        seen: set[str] = set()

        # Explicit dataSources array
        for ds in model.get("dataSources", []):
            name = ds.get("name", "")
            conn_string = ds.get("connectionString", "")
            if name and name not in seen:
                seen.add(name)
                database = ""
                conn_type = ""
                if conn_string:
                    conn_parts = _parse_connection_string(conn_string)
                    database = conn_parts.get("initial catalog", "")
                    if not database:
                        database = conn_parts.get("database", "")
                    provider = conn_parts.get("provider", "")
                    if provider:
                        conn_type = provider
                datasources.append(
                    DataSource(
                        name=name,
                        connection_type=conn_type,
                        connection_string=conn_string,
                        database=database,
                    )
                )
                logger.debug("PBIX: found data source '%s'", name)

        # Also scan table partition M expressions for Sql.Database(...)
        for table in model.get("tables", []):
            table_name = table.get("name", "")
            for partition in table.get("partitions", []):
                source = partition.get("source", {})
                if source.get("type", "").lower() != "m":
                    continue
                expression = source.get("expression", "")
                if isinstance(expression, list):
                    expression = "\n".join(expression)
                match = _SQL_DATABASE_RE.search(expression)
                if match:
                    server, db = match.group(1), match.group(2)
                    ds_name = f"Sql.Database {server}/{db}"
                    if ds_name not in seen:
                        seen.add(ds_name)
                        datasources.append(
                            DataSource(
                                name=ds_name,
                                connection_type="SQL",
                                database=db,
                                connection_string=f"Data Source={server};Initial Catalog={db}",
                            )
                        )
                        logger.debug(
                            "PBIX: found M partition data source '%s' in table '%s'",
                            ds_name,
                            table_name,
                        )

        return datasources

    def _extract_fields(self, model: dict[str, Any]) -> list[Field]:
        """Extract columns and measures from all tables."""
        fields: list[Field] = []

        for table in model.get("tables", []):
            table_name = table.get("name", "")

            for col in table.get("columns", []):
                name = col.get("name", "")
                if not name:
                    continue
                data_type = col.get("dataType", "")
                description = col.get("description", "")
                source_col = col.get("sourceColumn", "")
                alias = source_col if source_col and source_col != name else ""
                if not alias and description:
                    alias = description
                fields.append(
                    Field(
                        name=name,
                        alias=alias,
                        data_type=data_type,
                        role=_infer_role(data_type),
                        field_type="column",
                        datasource=table_name,
                    )
                )
                logger.debug("PBIX: column '%s' in table '%s'", name, table_name)

            for measure in table.get("measures", []):
                name = measure.get("name", "")
                if not name:
                    continue
                expression = measure.get("expression", "")
                if isinstance(expression, list):
                    expression = "\n".join(expression)
                description = measure.get("description", "")
                fields.append(
                    Field(
                        name=name,
                        alias=description,
                        field_type="measure",
                        role="measure",
                        formula=expression,
                        original_formula=expression,
                        formula_status="Success" if expression else "",
                        datasource=table_name,
                    )
                )
                logger.debug("PBIX: measure '%s' in table '%s'", name, table_name)

        return fields

    def _extract_relationships(self, model: dict[str, Any]) -> list[Relationship]:
        """Extract relationship definitions from the model."""
        relationships: list[Relationship] = []

        for rel in model.get("relationships", []):
            from_table = rel.get("fromTable", "")
            to_table = rel.get("toTable", "")
            if not from_table or not to_table:
                continue

            from_col = rel.get("fromColumn", "")
            to_col = rel.get("toColumn", "")
            cross_filter = rel.get("crossFilteringBehavior")
            join_type = _CROSS_FILTER_MAP.get(cross_filter, "") if cross_filter is not None else ""

            relationships.append(
                Relationship(
                    left_table=from_table,
                    right_table=to_table,
                    join_type=join_type,
                    left_fields=[from_col] if from_col else [],
                    right_fields=[to_col] if to_col else [],
                )
            )
            logger.debug("PBIX: relationship '%s' -> '%s'", from_table, to_table)

        return relationships

    def _extract_report_elements(self, layout: dict[str, Any]) -> list[ReportElement]:
        """Extract report pages (sections) as report elements."""
        elements: list[ReportElement] = []

        for section in layout.get("sections", []):
            name = section.get("displayName") or section.get("name", "")
            if not name:
                continue

            fields_used: list[str] = []
            seen_fields: set[str] = set()

            for vc in section.get("visualContainers", []):
                config_raw = vc.get("config", "")
                if not config_raw:
                    continue
                config = self._parse_nested_json(config_raw)
                if config is None:
                    continue
                for ref in self._collect_query_refs(config):
                    if ref not in seen_fields:
                        seen_fields.add(ref)
                        fields_used.append(ref)

            elements.append(
                ReportElement(
                    name=name,
                    element_type="page",
                    fields_used=fields_used,
                )
            )
            logger.debug("PBIX: found page '%s'", name)

        return elements

    def _extract_filters(self, layout: dict[str, Any]) -> list[Filter]:
        """Extract filter definitions from report-level and section-level filters."""
        filters: list[Filter] = []

        # Report-level filters
        report_filters_raw = layout.get("filters", "")
        if report_filters_raw:
            filters.extend(self._parse_filters_json(report_filters_raw, "report"))

        # Section-level filters
        for section in layout.get("sections", []):
            section_filters_raw = section.get("filters", "")
            if section_filters_raw:
                page_name = section.get("displayName") or section.get("name", "")
                filters.extend(self._parse_filters_json(section_filters_raw, f"page:{page_name}"))

        return filters

    # ------------------------------------------------------------------
    # JSON parsing utilities
    # ------------------------------------------------------------------

    def _parse_nested_json(self, raw: Any) -> Any:
        """Parse a value that may be a JSON string or already a dict/list."""
        if isinstance(raw, (dict, list)):
            return raw
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return None
        return None

    def _collect_query_refs(self, obj: Any) -> list[str]:
        """Recursively collect all 'queryRef' string values from nested JSON."""
        refs: list[str] = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "queryRef" and isinstance(v, str):
                    refs.append(v)
                else:
                    refs.extend(self._collect_query_refs(v))
        elif isinstance(obj, list):
            for item in obj:
                refs.extend(self._collect_query_refs(item))
        return refs

    def _parse_filters_json(self, raw: Any, scope: str) -> list[Filter]:
        """Parse a filters value (JSON string or list) into Filter objects."""
        filters: list[Filter] = []
        parsed = self._parse_nested_json(raw)
        if not isinstance(parsed, list):
            return filters
        for item in parsed:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            filter_type = item.get("type", "")
            if not name:
                continue
            filters.append(
                Filter(
                    name=name,
                    filter_type=filter_type,
                    scope=scope,
                )
            )
            logger.debug("PBIX: found filter '%s' (scope=%s)", name, scope)
        return filters
