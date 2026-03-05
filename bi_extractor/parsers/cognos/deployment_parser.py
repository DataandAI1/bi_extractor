"""Parser for IBM Cognos deployment archives (.cab).

Cognos deployment archives use Microsoft Cabinet (.cab) format and contain
XML report specifications, connection definitions, and content store objects
exported from the Cognos environment.
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
    Parameter,
    ReportElement,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)

_HAS_CABARCHIVE = False
try:
    import cabarchive  # type: ignore[import-untyped]

    _HAS_CABARCHIVE = True
except ImportError:
    cabarchive = None  # type: ignore[assignment]


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


class CognosDeploymentParser(BaseParser):
    """Parser for IBM Cognos .cab deployment archives.

    Cognos deployment archives contain XML report specifications, data source
    connections, and other content store objects. This parser extracts XML
    files from the archive and parses them for metadata.

    Requires the ``cabarchive`` package: ``pip install cabarchive``
    """

    extensions: ClassVar[list[str]] = [".cab"]
    tool: ClassVar[str] = "IBM Cognos Analytics"

    def check_dependencies(self) -> tuple[bool, str]:
        """Check if cabarchive is available."""
        if _HAS_CABARCHIVE:
            return True, ""
        return False, "pip install cabarchive  (required for .cab Cognos deployment archives)"

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse an IBM Cognos .cab deployment archive."""
        source = str(file_path)
        result = ExtractionResult(
            source_file=source,
            file_type=file_path.suffix.lower().lstrip("."),
            tool_name=self.tool,
        )

        if not _HAS_CABARCHIVE:
            result.errors.append(
                "cabarchive package not installed. "
                "Install with: pip install cabarchive"
            )
            return result

        try:
            cab = cabarchive.CabArchive(str(file_path))
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to open CAB archive {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        # Find XML files inside the archive
        xml_entries = [
            name for name in cab.keys()
            if name.lower().endswith(".xml")
        ]

        if not xml_entries:
            msg = f"No XML files found inside Cognos deployment archive {source}"
            logger.warning(msg)
            result.errors.append(msg)
            return result

        result.metadata["archive_entries"] = list(cab.keys())
        result.metadata["xml_entries"] = xml_entries

        # Parse each XML file for Cognos content
        for entry_name in xml_entries:
            try:
                data = cab[entry_name].buf
                root = ET.fromstring(data)  # noqa: S314
                self._extract_from_xml(root, entry_name, result)
            except ET.ParseError as exc:
                msg = f"XML parse error in {entry_name} inside {source}: {exc}"
                logger.warning(msg)
                result.errors.append(msg)
            except Exception as exc:  # noqa: BLE001
                msg = f"Error parsing {entry_name} inside {source}: {exc}"
                logger.warning(msg)
                result.errors.append(msg)

        return result

    def _extract_from_xml(
        self, root: ET.Element, entry_name: str, result: ExtractionResult
    ) -> None:
        """Extract metadata from a single XML document within the archive."""
        # Extract data sources
        for ds_el in _find_all_local(root, "dataSource"):
            name = _attr(ds_el, "name", "id")
            conn_type = _attr(ds_el, "connectionType", "type")
            conn_string = _attr(ds_el, "connectionString")
            result.datasources.append(
                DataSource(
                    name=name or entry_name,
                    connection_type=conn_type,
                    connection_string=conn_string,
                )
            )

        # Extract query items as fields
        for qi_el in _find_all_local(root, "queryItem"):
            name = _attr(qi_el, "name", "id")
            if not name:
                continue
            data_type = _attr(qi_el, "dataType", "type")
            expression = _attr(qi_el, "expression")
            if not expression:
                expression = _child_text(qi_el, "expression")
            result.fields.append(
                Field(
                    name=name,
                    data_type=data_type,
                    formula=expression,
                    datasource=entry_name,
                )
            )

        # Extract parameters
        for param_el in _find_all_local(root, "parameter"):
            name = _attr(param_el, "name", "id")
            if not name:
                continue
            result.parameters.append(
                Parameter(
                    name=name,
                    data_type=_attr(param_el, "dataType", "type"),
                    default_value=_attr(param_el, "defaultValue"),
                    prompt_text=_attr(param_el, "promptText", "displayName"),
                )
            )

        # Extract report/page elements
        for tag_name in ("report", "page", "query"):
            for el in _find_all_local(root, tag_name):
                name = _attr(el, "name", "id")
                if name:
                    result.report_elements.append(
                        ReportElement(
                            name=name,
                            element_type=tag_name,
                        )
                    )
