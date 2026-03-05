"""Parser for MicroStrategy project/object files (.mstr).

MSTR files are ZIP archives containing XML object definitions exported from
MicroStrategy Workstation or Object Manager. They describe data sources,
attributes, metrics, reports, and parameters.
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import ClassVar
from xml.etree import ElementTree as ET

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
    Filter,
    Parameter,
    ReportElement,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)

_MSTR_NS = "http://www.microstrategy.com/schema"


def _ns(tag: str) -> str:
    """Return namespaced tag."""
    return f"{{{_MSTR_NS}}}{tag}"


def _find_el(root: ET.Element, tag: str) -> ET.Element | None:
    """Find element by local tag name, with or without namespace."""
    el = root.find(f".//{_ns(tag)}")
    if el is not None:
        return el
    return root.find(f".//{tag}")


def _find_all_el(root: ET.Element, tag: str) -> list[ET.Element]:
    """Find all elements by local tag name, with or without namespace."""
    elements = root.findall(f".//{_ns(tag)}")
    if not elements:
        elements = root.findall(f".//{tag}")
    return elements


def _find_direct(parent: ET.Element, tag: str) -> list[ET.Element]:
    """Find direct children by local tag name, with or without namespace."""
    children = parent.findall(_ns(tag))
    if not children:
        children = parent.findall(tag)
    return children


class MstrParser(BaseParser):
    """Parse MicroStrategy project/object files (.mstr).

    MSTR files are ZIP archives containing one or more XML object definition
    files. Plain XML .mstr files (no ZIP wrapper) are also supported as a
    fallback.
    """

    extensions: ClassVar[list[str]] = [".mstr"]
    tool: ClassVar[str] = "MicroStrategy"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a single .mstr file.

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

        if not file_path.exists():
            msg = f"File not found: {file_str}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        roots = self._load_xml_roots(file_path, result)
        if not roots:
            return result

        try:
            for root in roots:
                self._extract_metadata(root, result)
                self._extract_datasources(root, result)
                self._extract_fields(root, result)
                self._extract_report_elements(root, result)
                self._extract_parameters(root, result)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error while extracting metadata from {file_str}: {exc}"
            logger.exception(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # File loading
    # ------------------------------------------------------------------

    def _load_xml_roots(
        self, file_path: Path, result: ExtractionResult
    ) -> list[ET.Element]:
        """Load XML roots from the file, trying ZIP first, then plain XML."""
        file_str = str(file_path)

        # Try ZIP archive first.
        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                roots: list[ET.Element] = []
                
                # MSTR dossiers can contain binary data, XML metadata, and cubes.
                # Skip known binary/data extensions to avoid reading huge datasets
                skip_exts = (".cube", ".delta", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".pdf", ".bin")
                
                for name in zf.namelist():
                    if name.lower().endswith(skip_exts):
                        continue
                        
                    # Quick heuristic to avoid reading huge binary blobs into memory
                    # Also handles files with no extension that might actually be XML definitions
                    try:
                        with zf.open(name) as f:
                            peek = f.read(100).lstrip()
                            # Check if it looks like XML (starts with '<' or UTF-8 BOM + '<')
                            if not peek.startswith(b"<") and not peek.startswith(b"\xef\xbb\xbf<"):
                                continue
                    except Exception:
                        continue
                        
                    try:
                        data = zf.read(name)
                        root = ET.fromstring(data)  # noqa: S314
                        roots.append(root)
                    except ET.ParseError as exc:
                        # Only log errors if the file explicitly claimed to be XML, reduce noise
                        if name.lower().endswith(".xml"):
                            msg = f"XML parse error in {name} within {file_str}: {exc}"
                            logger.error(msg)
                            result.errors.append(msg)
                            
                if not roots:
                    msg = f"No valid XML metadata found in ZIP archive: {file_str}"
                    logger.warning(msg)
                    result.errors.append(msg)
                    return []
                return roots
        except zipfile.BadZipFile:
            logger.debug("%s is not a ZIP archive, trying plain XML", file_str)
        except OSError as exc:
            msg = f"Cannot read {file_str}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return []

        # Fallback: try plain XML.
        try:
            tree = ET.parse(file_path)  # noqa: S314
            return [tree.getroot()]
        except ET.ParseError as exc:
            msg = f"XML parse error in {file_str}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return []
        except OSError as exc:
            msg = f"Cannot read {file_str}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return []

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------

    def _extract_metadata(self, root: ET.Element, result: ExtractionResult) -> None:
        """Extract project name and description from root element."""
        # The root may be <mstr:project> or <project>.
        project_name = root.get("name", "")
        description = root.get("description", "")
        if project_name and "project_name" not in result.metadata:
            result.metadata["project_name"] = project_name
            logger.debug("Project name: %s", project_name)
        if description and "description" not in result.metadata:
            result.metadata["description"] = description

    def _extract_datasources(
        self, root: ET.Element, result: ExtractionResult
    ) -> None:
        """Extract DataSource elements from <dataSources>/<dataSource>."""
        for ds_el in _find_all_el(root, "dataSource"):
            name = ds_el.get("name", "").strip()
            if not name:
                continue

            conn_type = ds_el.get("type", "").strip()
            conn_string = ds_el.get("connectionString", "").strip()
            database = ds_el.get("database", "").strip()
            schema = ds_el.get("schema", "").strip()

            tables = [
                t.get("name", "").strip()
                for t in _find_direct(ds_el, "table")
                if t.get("name", "").strip()
            ]

            result.datasources.append(
                DataSource(
                    name=name,
                    connection_type=conn_type,
                    connection_string=conn_string,
                    database=database,
                    schema=schema,
                    tables=tables,
                )
            )
            logger.debug("Found DataSource: %s (%s)", name, conn_type)

    def _extract_fields(self, root: ET.Element, result: ExtractionResult) -> None:
        """Extract Field elements from <attributes> and <metrics>."""
        # Attributes → field_type="attribute"
        for attr_el in _find_all_el(root, "attribute"):
            name = attr_el.get("name", "").strip()
            if not name:
                continue
            data_type = attr_el.get("dataType", "").strip()
            table = attr_el.get("table", "").strip()
            description = attr_el.get("description", "").strip()
            result.fields.append(
                Field(
                    name=name,
                    data_type=data_type,
                    role="dimension",
                    field_type="attribute",
                    datasource=table,
                    alias=description,
                )
            )
            logger.debug("Found attribute field: %s", name)

        # Metrics → field_type="metric"
        for metric_el in _find_all_el(root, "metric"):
            name = metric_el.get("name", "").strip()
            if not name:
                continue
            data_type = metric_el.get("dataType", "").strip()
            formula = metric_el.get("formula", "").strip()
            description = metric_el.get("description", "").strip()
            result.fields.append(
                Field(
                    name=name,
                    data_type=data_type,
                    role="measure",
                    field_type="metric",
                    formula=formula,
                    original_formula=formula,
                    formula_status="Success" if formula else "",
                    alias=description,
                )
            )
            logger.debug("Found metric field: %s", name)

    def _extract_report_elements(
        self, root: ET.Element, result: ExtractionResult
    ) -> None:
        """Extract ReportElement objects from <reports>/<report>."""
        for report_el in _find_all_el(root, "report"):
            name = report_el.get("name", "").strip()
            if not name:
                continue
            element_type = report_el.get("type", "").strip()

            # Collect referenced attribute and metric names.
            fields_used: list[str] = []
            for ref_el in _find_direct(report_el, "attribute"):
                ref = ref_el.get("ref", "").strip()
                if ref:
                    fields_used.append(ref)
            for ref_el in _find_direct(report_el, "metric"):
                ref = ref_el.get("ref", "").strip()
                if ref:
                    fields_used.append(ref)

            # Extract filters within this report.
            filters: list[Filter] = []
            for filter_el in _find_direct(report_el, "filter"):
                filter_name = filter_el.get("name", "").strip()
                expression = filter_el.get("expression", "").strip()
                f = Filter(
                    name=filter_name,
                    expression=expression,
                    scope=name,
                )
                filters.append(f)
                result.filters.append(f)
                logger.debug("Found filter: %s in report %s", filter_name, name)

            result.report_elements.append(
                ReportElement(
                    name=name,
                    element_type=element_type,
                    fields_used=fields_used,
                    filters=filters,
                )
            )
            logger.debug("Found report element: %s (%s)", name, element_type)

    def _extract_parameters(
        self, root: ET.Element, result: ExtractionResult
    ) -> None:
        """Extract Parameter elements from <parameters>/<parameter>."""
        for param_el in _find_all_el(root, "parameter"):
            name = param_el.get("name", "").strip()
            if not name:
                continue
            data_type = param_el.get("dataType", "").strip()
            default_value = param_el.get("defaultValue", "").strip()
            prompt_text = param_el.get("prompt", "").strip()
            result.parameters.append(
                Parameter(
                    name=name,
                    data_type=data_type,
                    default_value=default_value,
                    prompt_text=prompt_text,
                )
            )
            logger.debug("Found parameter: %s (type=%s)", name, data_type)
