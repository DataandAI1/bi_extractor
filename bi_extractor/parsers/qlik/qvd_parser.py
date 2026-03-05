"""Parser for QlikView Data files (.qvd).

QVD files contain a binary data extract preceded by an XML header that
describes the table structure, field definitions, and source metadata.
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
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# QVD NumberFormat/Type → normalized data_type
_NUMBER_FORMAT_TYPES: dict[str, str] = {
    "0": "unknown",
    "1": "integer",
    "2": "float",
    "3": "money",
    "4": "date",
    "5": "time",
    "6": "timestamp",
    "7": "string",
}


def _child_text(element: ET.Element, tag: str) -> str:
    """Return stripped text of first matching child element."""
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


class QvdParser(BaseParser):
    """Parser for QlikView Data .qvd files.

    QVD files consist of an XML header (describing table name, fields, and
    source metadata) followed by a null byte separator and raw binary data.
    Only the XML header is parsed; the binary section is ignored.
    """

    extensions: ClassVar[list[str]] = [".qvd"]
    tool: ClassVar[str] = "QlikView"

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a QlikView Data .qvd file and return normalized metadata."""
        source = str(file_path)
        result = ExtractionResult(
            source_file=source,
            file_type=file_path.suffix.lower().lstrip("."),
            tool_name=self.tool,
        )

        # --- Read binary content ---
        try:
            raw = file_path.read_bytes()
        except OSError as exc:
            msg = f"Cannot open {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        if not raw:
            msg = f"File is empty: {source}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        # --- Extract XML header (everything up to and including </QvdTableHeader>) ---
        end_tag = b"</QvdTableHeader>"
        end_pos = raw.find(end_tag)
        if end_pos == -1:
            msg = f"No QVD XML header found (missing </QvdTableHeader>) in {source}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        xml_bytes = raw[: end_pos + len(end_tag)]

        # --- Parse XML ---
        try:
            root = ET.fromstring(xml_bytes)  # noqa: S314
        except ET.ParseError as exc:
            msg = f"XML parse error in {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        try:
            self._populate_result(result, root)
        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error parsing {source}: {exc}"
            logger.exception(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _populate_result(self, result: ExtractionResult, root: ET.Element) -> None:
        """Extract all metadata from the parsed XML root element."""
        table_name = _child_text(root, "TableName")
        creator_doc = _child_text(root, "CreatorDoc")
        record_count_text = _child_text(root, "NoOfRecords")
        qv_build_no = _child_text(root, "QvBuildNo")
        create_time = _child_text(root, "CreateUtcTime")

        record_count: int | None = None
        if record_count_text:
            try:
                record_count = int(record_count_text)
            except ValueError:
                pass

        # --- DataSource ---
        ds = DataSource(
            name=table_name,
            connection_type="QVD",
            tables=[table_name] if table_name else [],
        )
        result.datasources.append(ds)
        logger.debug("QVD: table '%s' from '%s'", table_name, creator_doc)

        # --- Fields ---
        fields_el = root.find("Fields")
        if fields_el is not None:
            for field_el in fields_el.findall("QvdFieldHeader"):
                field_name = _child_text(field_el, "FieldName")
                if not field_name:
                    continue

                # Determine data type from NumberFormat/Type
                nf_el = field_el.find("NumberFormat")
                type_code = ""
                if nf_el is not None:
                    type_code = _child_text(nf_el, "Type")
                data_type = _NUMBER_FORMAT_TYPES.get(type_code, "unknown")

                comment = _child_text(field_el, "Comment")

                # Infer role from QVD data types
                role = ""
                if data_type in ("integer", "float", "money"):
                    role = "measure"
                elif data_type in ("string", "date", "time", "timestamp"):
                    role = "dimension"

                result.fields.append(
                    Field(
                        name=field_name,
                        alias=comment,
                        data_type=data_type,
                        role=role,
                        field_type="column",
                        datasource=table_name,
                    )
                )
                logger.debug("QVD: field '%s' type=%s", field_name, data_type)

        # --- Metadata ---
        if table_name:
            result.metadata["table_name"] = table_name
        if record_count is not None:
            result.metadata["record_count"] = record_count
        if creator_doc:
            result.metadata["creator_doc"] = creator_doc
        if qv_build_no:
            result.metadata["qv_build_no"] = qv_build_no
        if create_time:
            result.metadata["create_time"] = create_time
