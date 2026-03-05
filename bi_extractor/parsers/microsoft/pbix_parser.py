"""Parser for Power BI Desktop report files (.pbix).

PBIX files are ZIP archives containing a JSON-based data model schema
and report layout definition with pages, visuals, filters, and data connections.
"""

from __future__ import annotations

import io
import json
import logging
import re
import struct
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import unquote

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

# Regex to extract table names from M expression `shared` declarations.
# Matches:  shared TableName = ...  and  shared #"Table Name" = ...
_M_SHARED_RE = re.compile(
    r'shared\s+(?:#"([^"]+)"|(\w+))\s*=',
)

# Regex for common M data source functions beyond Sql.Database
_M_SOURCE_RE = re.compile(
    r'(Sql\.Database|OData\.Feed|Web\.Contents|AnalysisServices\.Database'
    r'|Oracle\.Database|Odbc\.DataSource|PostgreSQL\.Database'
    r'|MySQL\.Database|Csv\.Document|Excel\.Workbook'
    r'|Sql\.Databases|AzureStorage\.Blobs)\s*\(\s*"([^"]+)"',
    re.IGNORECASE,
)


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
            names = zf.namelist()
            model = self._read_json_entry(zf, "DataModelSchema", source, result)
            layout = self._read_json_entry(zf, "Report/Layout", source, result)
            connections = self._read_json_entry(zf, "Connections", source, result)

            # Read DataMashup (contains M expressions and column metadata).
            # Available in both legacy and V3 formats.
            mashup_raw = None
            if "DataMashup" in names:
                try:
                    mashup_raw = zf.read("DataMashup")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("PBIX: cannot read DataMashup: %s", exc)

            is_legacy = model is None and "DataModel" in names

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

            # Extract from DataMashup (M expressions + metadata XML).
            # For legacy files this is the primary source of fields/datasources;
            # for V3 files it can supplement with Power Query table names.
            if mashup_raw is not None:
                self._process_data_mashup(mashup_raw, result, is_legacy)

            # Supplement datasources from Connections entry if present
            if connections is not None:
                conn_ds = self._extract_connections(connections)
                existing = {ds.name for ds in result.datasources}
                for ds in conn_ds:
                    if ds.name not in existing:
                        result.datasources.append(ds)

            if layout is not None:
                result.report_elements = self._extract_report_elements(layout)
                result.filters = self._extract_filters(layout)

            if is_legacy and not result.fields:
                result.metadata["legacy_format"] = "true"

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

    def _extract_connections(
        self,
        connections: dict[str, Any],
    ) -> list[DataSource]:
        """Extract datasources from the Connections ZIP entry.

        The Connections entry is a JSON object with a ``"Connections"`` array,
        each having ``Name``, ``ConnectionString``, and ``PbiServiceModelId``.
        """
        datasources: list[DataSource] = []
        conn_list: list[dict[str, Any]] = connections.get("Connections", [])

        for conn in conn_list:
            if not isinstance(conn, dict):
                continue
            name = conn.get("Name", "")
            conn_string = conn.get("ConnectionString", "")
            if not name:
                continue
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
            logger.debug("PBIX: found connection '%s'", name)

        return datasources

    # ------------------------------------------------------------------
    # DataMashup parsing (legacy + V3 supplement)
    # ------------------------------------------------------------------

    def _process_data_mashup(
        self,
        mashup_raw: bytes,
        result: ExtractionResult,
        is_legacy: bool,
    ) -> None:
        """Parse DataMashup binary blob to extract M queries and column metadata.

        DataMashup format:
          4 bytes  — version (typically 0)
          4 bytes  — length of inner ZIP package
          N bytes  — inner ZIP (contains Formulas/*.m, Config/Package.xml)
          4 bytes  — length of permissions section
          M bytes  — permissions
          4 bytes  — length of metadata section
          K bytes  — metadata XML (column info per table)
        """
        if len(mashup_raw) < 8:
            return

        try:
            _version = struct.unpack_from("<I", mashup_raw, 0)[0]
            pkg_len = struct.unpack_from("<I", mashup_raw, 4)[0]
        except struct.error:
            return

        offset = 8
        if offset + pkg_len > len(mashup_raw):
            return

        pkg_data = mashup_raw[offset : offset + pkg_len]
        offset += pkg_len

        # Parse the inner ZIP for M formulas
        m_text = ""
        try:
            inner_zf = zipfile.ZipFile(io.BytesIO(pkg_data))
            for name in inner_zf.namelist():
                if name.endswith(".m"):
                    m_text += inner_zf.read(name).decode("utf-8", errors="replace")
                    m_text += "\n"
        except (zipfile.BadZipFile, OSError) as exc:
            logger.warning("PBIX: cannot read DataMashup inner ZIP: %s", exc)

        # Parse metadata XML section (after permissions)
        meta_xml_bytes = b""
        try:
            if offset + 4 <= len(mashup_raw):
                perm_len = struct.unpack_from("<I", mashup_raw, offset)[0]
                offset += 4 + perm_len
            if offset + 4 <= len(mashup_raw):
                meta_len = struct.unpack_from("<I", mashup_raw, offset)[0]
                offset += 4
                meta_xml_bytes = mashup_raw[offset : offset + meta_len]
        except struct.error:
            pass

        # Extract table names and datasources from M expressions
        existing_ds = {ds.name for ds in result.datasources}
        if m_text:
            self._extract_from_m_expressions(m_text, result, existing_ds, is_legacy)

        # Extract column metadata from the XML section
        if meta_xml_bytes and is_legacy:
            self._extract_mashup_columns(meta_xml_bytes, result)

    def _extract_from_m_expressions(
        self,
        m_text: str,
        result: ExtractionResult,
        existing_ds: set[str],
        is_legacy: bool,
    ) -> None:
        """Extract table names and datasources from Power Query M code."""
        # Extract datasources from M source functions
        seen_sources: set[str] = set(existing_ds)
        for match in _M_SOURCE_RE.finditer(m_text):
            func_name = match.group(1)
            first_arg = match.group(2)
            ds_name = f"{func_name} {first_arg}"
            if ds_name in seen_sources:
                continue
            seen_sources.add(ds_name)

            # Try to find database from Sql.Database("server", "db")
            database = ""
            conn_type = func_name.split(".")[0]
            sql_match = _SQL_DATABASE_RE.search(m_text)
            if sql_match and sql_match.group(1) == first_arg:
                database = sql_match.group(2)

            result.datasources.append(
                DataSource(
                    name=ds_name,
                    connection_type=conn_type,
                    database=database,
                    connection_string=first_arg,
                )
            )
            logger.debug("PBIX: found M data source '%s'", ds_name)

        # For legacy files, extract table names from shared declarations
        if is_legacy:
            existing_tables = {f.datasource for f in result.fields}
            for match in _M_SHARED_RE.finditer(m_text):
                table_name = match.group(1) or match.group(2)
                if table_name and table_name not in existing_tables:
                    existing_tables.add(table_name)
                    result.metadata.setdefault("mashup_tables", [])
                    result.metadata["mashup_tables"].append(table_name)
                    logger.debug("PBIX: found M shared table '%s'", table_name)

    def _extract_mashup_columns(
        self,
        meta_xml_bytes: bytes,
        result: ExtractionResult,
    ) -> None:
        """Extract column names from DataMashup metadata XML.

        The XML contains ``<Item>`` elements with ``<ItemLocation>`` identifying
        the table and ``<StableEntries>`` with ``RelationshipInfoContainer`` or
        ``FillColumnNames`` entries that list column names.
        """
        try:
            # Find XML boundaries — metadata may have leading binary bytes
            xml_start = meta_xml_bytes.find(b"<?xml")
            xml_end = meta_xml_bytes.find(b"</LocalPackageMetadataFile>")
            if xml_start < 0:
                return
            if xml_end >= 0:
                xml_data = meta_xml_bytes[xml_start : xml_end + len(b"</LocalPackageMetadataFile>")]
            else:
                xml_data = meta_xml_bytes[xml_start:]

            root = ET.fromstring(xml_data)
        except ET.ParseError as exc:
            logger.warning("PBIX: cannot parse DataMashup metadata XML: %s", exc)
            return

        for item in root.iter("Item"):
            loc = item.find("ItemLocation")
            if loc is None:
                continue
            item_type = (loc.findtext("ItemType") or "").strip()
            item_path = (loc.findtext("ItemPath") or "").strip()
            if item_type != "Formula" or not item_path:
                continue

            # item_path is like "Section1/TableName" — extract table name
            table_name = unquote(item_path.split("/")[-1])

            # Look for column names in StableEntries
            col_names: list[str] = []
            entries = item.find("StableEntries")
            if entries is None:
                continue

            for entry in entries.findall("Entry"):
                etype = entry.get("Type", "")
                evalue = entry.get("Value", "")

                if etype == "FillColumnNames" and evalue.startswith("s"):
                    try:
                        col_names = json.loads(evalue[1:])
                    except (json.JSONDecodeError, ValueError):
                        pass

                if not col_names and etype == "RelationshipInfoContainer" and evalue.startswith("s"):
                    try:
                        info = json.loads(evalue[1:])
                        for ident in info.get("columnIdentities", []):
                            if "{" in ident:
                                col_part = ident.split("{")[-1].rstrip("}")
                                col_names.append(col_part.split(",")[0])
                    except (json.JSONDecodeError, ValueError, KeyError):
                        pass

            # Add columns as fields
            for col_name in col_names:
                if not col_name:
                    continue
                result.fields.append(
                    Field(
                        name=col_name,
                        field_type="column",
                        datasource=table_name,
                    )
                )
            if col_names:
                logger.debug(
                    "PBIX: extracted %d columns for table '%s' from DataMashup",
                    len(col_names),
                    table_name,
                )

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
