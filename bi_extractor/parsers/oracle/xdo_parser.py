"""Parser for Oracle BI Publisher data template files (.xdo, .xdoz)."""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
    Parameter,
    ReportElement,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)


def _attr(element: ET.Element, *names: str) -> str:
    """Return the first matching attribute value (case-insensitive fallback)."""
    for name in names:
        val = element.get(name, "")
        if val:
            return val.strip()
    return ""


def _child_text(element: ET.Element, tag: str) -> str:
    """Return stripped text of first matching child element."""
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


class OracleXdoParser(BaseParser):
    """Parser for Oracle BI Publisher .xdo and .xdoz files.

    .xdo files are XML data templates containing data model definitions,
    SQL queries, parameters, and field bindings used by Oracle BI Publisher.

    .xdoz files are ZIP archives containing one or more .xdo files. This
    parser extracts the inner .xdo from the archive and parses it as XML.
    """

    extensions: list[str] = [".xdo", ".xdoz"]
    tool: str = "Oracle BI Publisher"

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse an Oracle BI Publisher .xdo or .xdoz file."""
        source = str(file_path)
        suffix = file_path.suffix.lower()
        result = ExtractionResult(
            source_file=source,
            file_type=suffix,
            tool_name=self.tool,
        )

        try:
            root = self._load_xml(file_path, suffix, result)
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to load {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        if root is None:
            # Error already appended inside _load_xml
            return result

        try:
            result.datasources = self._extract_datasources(root)
            result.fields = self._extract_fields(root)
            result.parameters = self._extract_parameters(root)
            result.report_elements = self._extract_report_elements(root)

            # Collect SQL queries into metadata
            sql_map = self._extract_sql_queries(root)
            if sql_map:
                result.metadata["sql_queries"] = sql_map

            # Store template/report name if present
            template_name = _attr(root, "name", "reportName", "dataObjectName")
            if template_name:
                result.metadata["template_name"] = template_name

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error parsing {source}: {exc}"
            logger.exception(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # Loading helpers
    # ------------------------------------------------------------------

    def _load_xml(
        self, file_path: Path, suffix: str, result: ExtractionResult
    ) -> ET.Element | None:
        """Return the root XML element, handling both .xdo and .xdoz."""
        if suffix == ".xdoz":
            return self._load_from_zip(file_path, result)
        return self._parse_xml_file(file_path, result)

    def _load_from_zip(
        self, file_path: Path, result: ExtractionResult
    ) -> ET.Element | None:
        """Extract the first .xdo entry from a .xdoz ZIP archive and parse it."""
        source = str(file_path)
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                xdo_names = [n for n in zf.namelist() if n.lower().endswith(".xdo")]
                if not xdo_names:
                    msg = f"No .xdo file found inside archive {source}"
                    logger.error(msg)
                    result.errors.append(msg)
                    return None
                # Use the first .xdo found; log if there are multiple
                if len(xdo_names) > 1:
                    logger.debug(
                        "Multiple .xdo files in %s; using '%s'", source, xdo_names[0]
                    )
                with zf.open(xdo_names[0]) as xdo_file:
                    try:
                        tree = ET.parse(xdo_file)  # noqa: S314
                        return tree.getroot()
                    except ET.ParseError as exc:
                        msg = f"XML parse error in {xdo_names[0]} inside {source}: {exc}"
                        logger.error(msg)
                        result.errors.append(msg)
                        return None
        except zipfile.BadZipFile as exc:
            msg = f"Invalid ZIP archive {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return None
        except OSError as exc:
            msg = f"Cannot open {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return None

    def _parse_xml_file(
        self, file_path: Path, result: ExtractionResult
    ) -> ET.Element | None:
        """Parse a plain XML .xdo file and return the root element."""
        source = str(file_path)
        try:
            tree = ET.parse(file_path)  # noqa: S314
            return tree.getroot()
        except ET.ParseError as exc:
            msg = f"XML parse error in {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return None
        except OSError as exc:
            msg = f"Cannot open {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return None

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_datasources(self, root: ET.Element) -> list[DataSource]:
        """Extract data source definitions from the data template."""
        datasources: list[DataSource] = []

        # XDO data templates may declare data sources under various paths:
        #   <dataTemplate><dataSources><dataSource .../>
        #   <dataModel><dataSources><dataSource .../>
        for ds_el in root.iter("dataSource"):
            name = _attr(ds_el, "name", "id")
            conn_type = _attr(ds_el, "type", "dataSourceRef")
            conn_string = _attr(ds_el, "connectionString", "url", "jndiName")
            database = _attr(ds_el, "database", "schema")

            datasources.append(
                DataSource(
                    name=name,
                    connection_type=conn_type,
                    connection_string=conn_string,
                    database=database,
                )
            )
            logger.debug("XDO: found data source '%s' (%s)", name, conn_type)

        return datasources

    def _extract_fields(self, root: ET.Element) -> list[Field]:
        """Extract field/element bindings from dataStructure or group elements."""
        fields: list[Field] = []

        # Fields are typically declared under <dataStructure><group><element>
        # or directly under <dataTemplate><dataStructure><element>
        for el in root.iter("element"):
            name = _attr(el, "name", "value")
            data_type = _attr(el, "dataType", "type")
            datasource = _attr(el, "dataSourceRef", "refDataSource", "")

            if not name:
                continue

            # Infer role from XDO data types
            role = ""
            if data_type:
                lower_type = data_type.lower()
                if lower_type in (
                    "number", "integer", "int", "float", "double",
                    "decimal", "long", "currency", "numeric",
                ):
                    role = "measure"
                else:
                    role = "dimension"

            fields.append(
                Field(
                    name=name,
                    data_type=data_type,
                    field_type="column",
                    role=role,
                    datasource=datasource,
                )
            )
            logger.debug("XDO: found field '%s' (%s)", name, data_type)

        return fields

    def _extract_parameters(self, root: ET.Element) -> list[Parameter]:
        """Extract <parameter> elements from the data template."""
        parameters: list[Parameter] = []

        for param_el in root.iter("parameter"):
            name = _attr(param_el, "name", "id")
            data_type = _attr(param_el, "dataType", "type")
            default_value = _attr(param_el, "defaultValue", "default")
            # In some XDO schemas the display name acts as a prompt
            prompt_text = _attr(param_el, "displayName", "label", "promptText")

            if not name:
                continue

            parameters.append(
                Parameter(
                    name=name,
                    data_type=data_type,
                    default_value=default_value,
                    prompt_text=prompt_text,
                )
            )
            logger.debug("XDO: found parameter '%s'", name)

        return parameters

    def _extract_report_elements(self, root: ET.Element) -> list[ReportElement]:
        """Extract group/query elements as report structure elements."""
        elements: list[ReportElement] = []

        for group_el in root.iter("group"):
            name = _attr(group_el, "name", "id")
            if not name:
                continue
            elements.append(ReportElement(name=name, element_type="group"))
            logger.debug("XDO: found group element '%s'", name)

        return elements

    def _extract_sql_queries(self, root: ET.Element) -> dict[str, str]:
        """Extract SQL query text from <sqlStatement> or <sql> elements."""
        sql_map: dict[str, str] = {}

        # Oracle XDO uses <sqlStatement> or <sql> tags
        for tag_name in ("sqlStatement", "sql", "query"):
            for idx, sql_el in enumerate(root.iter(tag_name)):
                sql_text = (sql_el.text or "").strip()
                if not sql_text:
                    continue
                key = _attr(sql_el, "name", "id") or f"{tag_name}_{idx}"
                sql_map[key] = sql_text
                logger.debug("XDO: found SQL '%s'", key)

        return sql_map
