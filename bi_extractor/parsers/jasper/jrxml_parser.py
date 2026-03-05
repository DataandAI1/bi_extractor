"""JasperReports JRXML parser.

Extracts metadata from .jrxml files (JasperReports XML report definitions).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any
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

# JasperReports XML namespace
_NS = "http://jasperreports.sourceforge.net/jasperreports"
_NSP = f"{{{_NS}}}"  # Clark notation prefix

# Mapping from Java class names to normalized type strings
_JAVA_TYPE_MAP: dict[str, str] = {
    "java.lang.String": "string",
    "java.lang.Character": "string",
    "java.lang.Boolean": "boolean",
    "java.lang.Byte": "integer",
    "java.lang.Short": "integer",
    "java.lang.Integer": "integer",
    "java.lang.Long": "integer",
    "java.lang.Float": "float",
    "java.lang.Double": "float",
    "java.math.BigDecimal": "float",
    "java.math.BigInteger": "integer",
    "java.util.Date": "date",
    "java.sql.Date": "date",
    "java.sql.Time": "time",
    "java.sql.Timestamp": "datetime",
    "java.util.Collection": "list",
    "java.util.List": "list",
}

# Band element tag names (without namespace prefix)
_BAND_TAGS = {
    "background",
    "title",
    "pageHeader",
    "columnHeader",
    "detail",
    "columnFooter",
    "pageFooter",
    "lastPageFooter",
    "summary",
    "noData",
}

# Regex to find $F{fieldName} references in expressions
_FIELD_REF_RE = re.compile(r'\$F\{([^}]+)\}')

# Numeric data types that indicate a measure role
_NUMERIC_TYPES = {"integer", "float", "long", "double", "decimal"}


def _infer_role(data_type: str) -> str:
    """Infer dimension/measure role from normalized type."""
    if not data_type:
        return ""
    if data_type.lower() in _NUMERIC_TYPES:
        return "measure"
    return "dimension"


def _normalize_type(java_class: str) -> str:
    """Map a Java class name to a normalized type string."""
    # Strip leading/trailing whitespace and handle short names
    java_class = java_class.strip()
    if java_class in _JAVA_TYPE_MAP:
        return _JAVA_TYPE_MAP[java_class]
    # Handle short names like "String", "Integer" without package prefix
    for key, value in _JAVA_TYPE_MAP.items():
        if key.endswith(f".{java_class}"):
            return value
    return java_class.lower()


def _tag(local: str) -> str:
    """Return Clark-notation tag for a JasperReports namespace element."""
    return f"{_NSP}{local}"


def _find_text(element: ET.Element, local_tag: str) -> str:
    """Return stripped text of first matching child, or empty string."""
    child = element.find(_tag(local_tag))
    if child is not None and child.text:
        return child.text.strip()
    return ""


class JrxmlParser(BaseParser):
    """Parser for JasperReports .jrxml report definition files."""

    extensions: list[str] = [".jrxml"]
    tool: str = "JasperReports"

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a .jrxml file and return normalized extraction result."""
        source = str(file_path)
        result = ExtractionResult(
            source_file=source,
            file_type=".jrxml",
            tool_name=self.tool,
        )

        try:
            tree = ET.parse(file_path)  # noqa: S314  (local trusted files)
            root = tree.getroot()
        except ET.ParseError as exc:
            msg = f"XML parse error in {file_path.name}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result
        except OSError as exc:
            msg = f"Cannot read {file_path.name}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        try:
            self._extract_metadata(root, result)
            self._extract_datasource(root, result)
            self._extract_query(root, result)
            self._extract_fields(root, result)
            self._extract_variables(root, result)
            self._extract_parameters(root, result)
            self._extract_bands(root, result)
            self._track_field_usage(root, result)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error parsing {file_path.name}: {exc}"
            logger.exception(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # Private extraction helpers
    # ------------------------------------------------------------------

    def _extract_metadata(self, root: ET.Element, result: ExtractionResult) -> None:
        """Store top-level jasperReport attributes as metadata."""
        attrs: dict[str, Any] = {}
        for attr_name in ("name", "pageWidth", "pageHeight", "columnWidth", "language"):
            val = root.get(attr_name)
            if val is not None:
                attrs[attr_name] = val
        if attrs:
            result.metadata.update(attrs)
            logger.debug("Extracted jasperReport attributes: %s", list(attrs.keys()))

    def _extract_datasource(self, root: ET.Element, result: ExtractionResult) -> None:
        """Extract connection/datasource info if present."""
        # Look for a queryString to infer a JDBC datasource
        query_el = root.find(f".//{_tag('queryString')}")
        report_name = root.get("name", "")

        # Try explicit dataSource element (less common in pure JRXML)
        ds_el = root.find(f".//{_tag('dataSource')}")
        conn_type = ""
        conn_string = ""

        if ds_el is not None:
            conn_type = ds_el.get("type", ds_el.get("class", ""))
            conn_string = ds_el.get("connectionString", ds_el.get("url", ""))

        if query_el is not None and not conn_type:
            conn_type = "jdbc"

        if conn_type or query_el is not None:
            ds = DataSource(
                name=report_name or file_path_from_result(result),
                connection_type=conn_type,
                connection_string=conn_string,
            )
            result.datasources.append(ds)
            logger.debug("Extracted datasource: %s (type=%s)", ds.name, ds.connection_type)

    def _extract_query(self, root: ET.Element, result: ExtractionResult) -> None:
        """Extract SQL query string and store in metadata."""
        query_el = root.find(f".//{_tag('queryString')}")
        if query_el is None:
            return
        # Query text may be in a CDATA section — ET handles that transparently
        query_text = (query_el.text or "").strip()
        if query_text:
            result.metadata["query"] = query_text
            logger.debug("Extracted queryString (%d chars)", len(query_text))

    def _extract_fields(self, root: ET.Element, result: ExtractionResult) -> None:
        """Extract <field> elements as Field objects with field_type='regular'."""
        # Determine datasource name from result (set by _extract_datasource)
        ds_name = result.datasources[0].name if result.datasources else ""
        for field_el in root.findall(f".//{_tag('field')}"):
            name = field_el.get("name", "").strip()
            if not name:
                logger.warning("Skipping <field> with no name attribute")
                continue
            java_class = field_el.get("class", "")
            data_type = _normalize_type(java_class) if java_class else ""
            description = _find_text(field_el, "fieldDescription")
            result.fields.append(
                Field(
                    name=name,
                    alias=description,
                    data_type=data_type,
                    role=_infer_role(data_type),
                    field_type="regular",
                    datasource=ds_name,
                )
            )
        logger.debug("Extracted %d fields", sum(1 for f in result.fields if f.field_type == "regular"))

    def _extract_variables(self, root: ET.Element, result: ExtractionResult) -> None:
        """Extract <variable> elements as Field objects with field_type='calculated'."""
        ds_name = result.datasources[0].name if result.datasources else ""
        for var_el in root.findall(f".//{_tag('variable')}"):
            name = var_el.get("name", "").strip()
            if not name:
                logger.warning("Skipping <variable> with no name attribute")
                continue
            java_class = var_el.get("class", "")
            data_type = _normalize_type(java_class) if java_class else ""
            formula = _find_text(var_el, "variableExpression")
            result.fields.append(
                Field(
                    name=name,
                    data_type=data_type,
                    role=_infer_role(data_type),
                    field_type="calculated",
                    formula=formula,
                    original_formula=formula,
                    formula_status="Success" if formula else "",
                    datasource=ds_name,
                )
            )
        logger.debug(
            "Extracted %d variables",
            sum(1 for f in result.fields if f.field_type == "calculated"),
        )

    def _extract_parameters(self, root: ET.Element, result: ExtractionResult) -> None:
        """Extract <parameter> elements as Parameter objects."""
        for param_el in root.findall(f".//{_tag('parameter')}"):
            name = param_el.get("name", "").strip()
            if not name:
                logger.warning("Skipping <parameter> with no name attribute")
                continue
            # Skip built-in JasperReports system parameters
            if name.startswith("REPORT_"):
                continue
            java_class = param_el.get("class", "")
            data_type = _normalize_type(java_class) if java_class else ""
            default = _find_text(param_el, "defaultValueExpression")
            result.parameters.append(
                Parameter(
                    name=name,
                    data_type=data_type,
                    default_value=default,
                )
            )
        logger.debug("Extracted %d parameters", len(result.parameters))

    def _extract_bands(self, root: ET.Element, result: ExtractionResult) -> None:
        """Extract report band sections as ReportElement objects."""
        # Bands can appear directly under jasperReport or under <detail>/<group>
        seen: set[str] = set()
        for band_tag in _BAND_TAGS:
            for band_el in root.iter(_tag(band_tag)):
                if band_tag in seen:
                    # Avoid duplicates for repeated tags (e.g. multiple <detail>)
                    break
                seen.add(band_tag)
                result.report_elements.append(
                    ReportElement(
                        name=band_tag,
                        element_type="section",
                    )
                )
        # Also handle <group> elements — each group has a name attribute
        for group_el in root.findall(f".//{_tag('group')}"):
            group_name = group_el.get("name", "").strip()
            if group_name:
                result.report_elements.append(
                    ReportElement(
                        name=group_name,
                        element_type="group",
                    )
                )
        logger.debug("Extracted %d report elements", len(result.report_elements))

    def _track_field_usage(self, root: ET.Element, result: ExtractionResult) -> None:
        """Scan textFieldExpression elements for $F{name} references and attach to bands."""
        # Collect all $F{...} references across all textFieldExpression elements
        all_refs: set[str] = set()
        for expr_el in root.findall(f".//{_tag('textFieldExpression')}"):
            text = expr_el.text or ""
            all_refs.update(_FIELD_REF_RE.findall(text))

        if not all_refs:
            return

        # Attach the full reference set to every section-type element
        # (band-level attribution per-expression is complex; top-level list is standard)
        for element in result.report_elements:
            if element.element_type == "section":
                element.fields_used = sorted(all_refs)

        logger.debug("Tracked %d field references in textFieldExpressions", len(all_refs))


def file_path_from_result(result: ExtractionResult) -> str:
    """Return the bare filename from a result's source_file path."""
    return Path(result.source_file).stem
