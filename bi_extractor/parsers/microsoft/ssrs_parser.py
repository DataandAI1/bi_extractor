"""Parser for SSRS / Power BI Paginated Reports (.rdl, .rdlc files).

RDL files are XML documents following Microsoft's Report Definition Language
schema. Multiple namespace versions are supported (2008, 2010, 2016) as well
as namespace-free documents.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
    Parameter,
    ReportElement,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# All known RDL namespace URIs in chronological order.
_RDL_NAMESPACES: list[str] = [
    "http://schemas.microsoft.com/sqlserver/reporting/2008/01/reportdefinition",
    "http://schemas.microsoft.com/sqlserver/reporting/2010/01/reportdefinition",
    "http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition",
    "",  # namespace-free documents
]


def _ns(tag: str, namespace: str) -> str:
    """Return a Clark-notation tag string for the given namespace."""
    if namespace:
        return f"{{{namespace}}}{tag}"
    return tag


def _detect_namespace(root: ET.Element) -> str:
    """Detect which RDL namespace the document uses.

    Inspects the root element tag. If it has a namespace, returns it.
    Falls back to the empty string for namespace-free documents.
    """
    tag = root.tag
    if tag.startswith("{"):
        end = tag.index("}")
        return tag[1:end]
    return ""


def _find_text(element: ET.Element, path: str, ns: str) -> str:
    """Return the text of the first matching child, or empty string."""
    # Build the namespaced path fragment by fragment so each step is prefixed.
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


def _iter_children(element: ET.Element, tag: str, ns: str):
    """Yield direct children matching the given tag under namespace ns."""
    return element.iter(_ns(tag, ns))


class SsrsParser(BaseParser):
    """Parse SSRS / Power BI Paginated Report files (.rdl, .rdlc).

    Extracts data sources, dataset fields, report parameters, and report
    items (Tablix, Chart, TextBox, etc.) from Report Definition Language XML.
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
            self._extract_datasources(root, ns, result)
            self._extract_datasets(root, ns, result)
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
        """Extract DataSource elements from //DataSources/DataSource."""
        datasources_el = root.find(_ns("DataSources", ns))
        if datasources_el is None:
            logger.debug("No <DataSources> element found.")
            return

        for ds_el in datasources_el.findall(_ns("DataSource", ns)):
            name = ds_el.get("Name", "").strip()
            if not name:
                continue

            conn_props = ds_el.find(_ns("ConnectionProperties", ns))
            connection_type = ""
            connection_string = ""

            if conn_props is not None:
                provider_el = conn_props.find(_ns("DataProvider", ns))
                if provider_el is not None:
                    connection_type = (provider_el.text or "").strip()

                connect_el = conn_props.find(_ns("ConnectString", ns))
                if connect_el is not None:
                    connection_string = (connect_el.text or "").strip()

            result.datasources.append(
                DataSource(
                    name=name,
                    connection_type=connection_type,
                    connection_string=connection_string,
                )
            )
            logger.debug("Found DataSource: %s (%s)", name, connection_type)

    def _extract_datasets(
        self, root: ET.Element, ns: str, result: ExtractionResult
    ) -> None:
        """Extract Fields and CommandText from //DataSets/DataSet elements."""
        datasets_el = root.find(_ns("DataSets", ns))
        if datasets_el is None:
            logger.debug("No <DataSets> element found.")
            return

        queries: list[str] = []

        for dataset_el in datasets_el.findall(_ns("DataSet", ns)):
            dataset_name = dataset_el.get("Name", "").strip()

            # Resolve the data source name for this dataset.
            datasource_ref = _find_text(dataset_el, "Query/DataSourceName", ns)

            # Extract CommandText.
            command_text = _find_text(dataset_el, "Query/CommandText", ns)
            if command_text:
                label = f"{dataset_name}: {command_text}" if dataset_name else command_text
                queries.append(label)

            # Extract Fields.
            fields_el = dataset_el.find(_ns("Fields", ns))
            if fields_el is None:
                continue

            for field_el in fields_el.findall(_ns("Field", ns)):
                field_name = field_el.get("Name", "").strip()
                if not field_name:
                    continue

                type_el = field_el.find(_ns("TypeName", ns))
                data_type = (type_el.text or "").strip() if type_el is not None else ""

                result.fields.append(
                    Field(
                        name=field_name,
                        data_type=data_type,
                        field_type="regular",
                        datasource=datasource_ref,
                    )
                )
                logger.debug(
                    "Found Field: %s (type=%s, ds=%s)", field_name, data_type, datasource_ref
                )

        if queries:
            result.metadata["queries"] = queries

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

            # Allowed values — ValidValues/ParameterValue/Value.
            allowed: list[str] = []
            valid_vals_el = param_el.find(_ns("ValidValues", ns))
            if valid_vals_el is not None:
                for pv_el in valid_vals_el.findall(_ns("ParameterValue", ns)):
                    val_el = pv_el.find(_ns("Value", ns))
                    if val_el is not None and val_el.text:
                        allowed.append(val_el.text.strip())

            result.parameters.append(
                Parameter(
                    name=name,
                    data_type=data_type,
                    default_value=default_value,
                    allowed_values=allowed,
                    prompt_text=prompt_text,
                )
            )
            logger.debug("Found Parameter: %s (type=%s)", name, data_type)

    def _extract_report_items(
        self, root: ET.Element, ns: str, result: ExtractionResult
    ) -> None:
        """Extract top-level report items (Tablix, Chart, TextBox, etc.) from Body."""
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
            result.report_elements.append(
                ReportElement(
                    name=name,
                    element_type=tag,
                )
            )
            logger.debug("Found ReportElement: %s (%s)", name, tag)
