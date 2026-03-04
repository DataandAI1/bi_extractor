"""Parser for Tableau Data Source files (.tds and .tdsx).

.tds files are XML containing only the datasource section (no worksheets).
.tdsx files are ZIP archives containing a .tds file inside.
"""

from __future__ import annotations

import logging
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class TableauTdsParser(BaseParser):
    """Parse Tableau Data Source files (.tds) and packaged data sources (.tdsx)."""

    extensions: list[str] = [".tds", ".tdsx"]
    tool: str = "Tableau"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a .tds or .tdsx file and return normalised metadata.

        Never raises — errors are captured in ExtractionResult.errors.
        """
        suffix = file_path.suffix.lower()
        file_type = suffix.lstrip(".")

        try:
            root = self._load_xml(file_path, suffix)
        except Exception as exc:
            msg = f"Failed to load {file_path.name}: {exc}"
            logger.error(msg)
            return ExtractionResult.error_result(
                source_file=str(file_path),
                file_type=file_type,
                tool_name=self.tool,
                error=msg,
            )

        result = ExtractionResult(
            source_file=str(file_path),
            file_type=file_type,
            tool_name=self.tool,
            # No worksheets in a data-source file
            report_elements=[],
        )

        try:
            self._extract_datasources(root, result)
            self._extract_fields(root, result)
        except Exception as exc:
            msg = f"Error extracting metadata from {file_path.name}: {exc}"
            logger.error(msg)
            result.errors.append(msg)

        logger.debug(
            "Parsed %s: %d datasource(s), %d field(s)",
            file_path.name,
            len(result.datasources),
            len(result.fields),
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_xml(self, file_path: Path, suffix: str) -> ET.Element:
        """Return the XML root element from a .tds or .tdsx file."""
        if suffix == ".tdsx":
            return self._load_from_zip(file_path)
        return ET.parse(file_path).getroot()

    def _load_from_zip(self, file_path: Path) -> ET.Element:
        """Extract the inner .tds from a .tdsx ZIP and parse it."""
        with zipfile.ZipFile(file_path, "r") as zf:
            tds_name = next(
                (n for n in zf.namelist() if n.lower().endswith(".tds")),
                None,
            )
            if tds_name is None:
                raise ValueError(f"No .tds file found inside {file_path.name}")
            with zf.open(tds_name) as fh:
                return ET.parse(fh).getroot()

    # ------------------------------------------------------------------
    # Extraction methods
    # ------------------------------------------------------------------

    def _extract_datasources(self, root: ET.Element, result: ExtractionResult) -> None:
        """Populate result.datasources from <datasource> elements.

        A .tds file may be the <datasource> element itself as the root, or it
        may wrap one or more <datasource> children.
        """
        # If the root IS a datasource, treat it directly
        candidates: list[ET.Element] = []
        if root.tag == "datasource":
            candidates = [root]
        else:
            candidates = root.findall(".//datasource")

        for ds_elem in candidates:
            ds_name = ds_elem.get("name", "")
            ds_caption = ds_elem.get("caption", ds_name)

            conn_type = ""
            conn_string = ""
            database = ""
            schema = ""
            tables: list[str] = []

            conn = ds_elem.find(".//connection")
            if conn is not None:
                conn_type = conn.get("class", "")
                server = conn.get("server", "")
                filename = conn.get("filename", "")
                db = conn.get("database", "")
                database = db or filename or server
                schema = conn.get("schema", "")
                # Build a simple connection string from the most informative fields
                parts = [p for p in [server, db, filename] if p]
                conn_string = "/".join(parts) if parts else ""

            # Collect referenced table names from <relation> elements
            for rel in ds_elem.findall(".//relation"):
                table = rel.get("table", "") or rel.get("name", "")
                if table and table not in tables:
                    tables.append(table)

            result.datasources.append(
                DataSource(
                    name=ds_name,
                    alias=ds_caption,
                    connection_type=conn_type,
                    connection_string=conn_string,
                    database=database,
                    schema=schema,
                    tables=tables,
                )
            )

    def _extract_fields(self, root: ET.Element, result: ExtractionResult) -> None:
        """Populate result.fields from <column> elements inside datasources."""
        # Build a calc-ID → caption map first (needed for formula cleaning)
        calc_id_map: dict[str, str] = self._build_calc_id_map(root)

        # Determine parent datasource elements (same logic as _extract_datasources)
        if root.tag == "datasource":
            ds_elements = [root]
        else:
            ds_elements = root.findall(".//datasource")

        seen: set[tuple[str, str]] = set()

        for ds_elem in ds_elements:
            ds_name = ds_elem.get("name", "")

            for col in ds_elem.findall(".//column"):
                field_name = col.get("name", "")
                if not field_name:
                    continue

                dedup = (field_name, ds_name)
                if dedup in seen:
                    continue
                seen.add(dedup)

                caption = col.get("caption", field_name)
                data_type = col.get("datatype", "")
                role = col.get("role", "")

                formula = ""
                original_formula = ""
                formula_status = ""
                field_type = self._determine_field_type(col)

                calc_elem = col.find(".//calculation")
                if calc_elem is not None:
                    raw = calc_elem.get("formula", "")
                    original_formula = raw
                    formula = self._resolve_formula(raw, calc_id_map)
                    formula_status = "resolved" if formula != raw and raw else (
                        "no_formula" if not raw else "raw"
                    )

                result.fields.append(
                    Field(
                        name=field_name,
                        alias=caption,
                        data_type=data_type,
                        role=role,
                        field_type=field_type,
                        formula=formula,
                        original_formula=original_formula,
                        formula_status=formula_status,
                        datasource=ds_name,
                    )
                )

        # Also capture standalone <calculation> elements not already in a <column>
        existing_names = {f.name for f in result.fields}
        for calc in root.findall(".//calculation"):
            calc_name = calc.get("name", "")
            if not calc_name or calc_name in existing_names:
                continue
            caption = calc.get("caption", calc_name)
            raw = calc.get("formula", "")
            formula = self._resolve_formula(raw, calc_id_map)
            result.fields.append(
                Field(
                    name=calc_name,
                    alias=caption,
                    data_type=calc.get("datatype", ""),
                    role=calc.get("role", ""),
                    field_type="Calculated Field",
                    formula=formula,
                    original_formula=raw,
                    formula_status="resolved" if formula != raw and raw else (
                        "no_formula" if not raw else "raw"
                    ),
                    datasource="",
                )
            )
            existing_names.add(calc_name)

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_field_type(col: ET.Element) -> str:
        """Determine the human-readable field type from a <column> element."""
        calc_elem = col.find(".//calculation")
        if calc_elem is not None:
            calc_class = calc_elem.get("class", "")
            if "tableau" in calc_class.lower():
                return "Table Calculation"
            return "Calculated Field"
        role = col.get("role", "")
        if role == "measure":
            agg = col.get("aggregation", "")
            return "Aggregated Measure" if agg else "Measure"
        return "Dimension"

    @staticmethod
    def _build_calc_id_map(root: ET.Element) -> dict[str, str]:
        """Build a mapping of calculation internal IDs to display captions."""
        calc_map: dict[str, str] = {}
        for col in root.findall(".//column"):
            calc_elem = col.find(".//calculation")
            if calc_elem is not None:
                calc_id = calc_elem.get("id", "")
                if calc_id:
                    caption = col.get("caption", col.get("name", ""))
                    if caption:
                        calc_map[calc_id] = caption
        for calc in root.findall(".//calculation"):
            calc_id = calc.get("id", "")
            if calc_id:
                caption = calc.get("caption", calc.get("name", ""))
                if caption:
                    calc_map[calc_id] = caption
        return calc_map

    @staticmethod
    def _resolve_formula(raw_formula: str, calc_map: dict[str, str]) -> str:
        """Replace internal calculation IDs with human-readable names."""
        if not raw_formula or not calc_map:
            return raw_formula
        import re

        result = raw_formula

        def sub(match: re.Match) -> str:
            calc_id = match.group(1)
            return f"[{calc_map[calc_id]}]" if calc_id in calc_map else match.group(0)

        result = re.sub(r"\[Calculation_(\d+)\]", sub, result)
        result = re.sub(r"@\{(\d+)\}", sub, result)
        result = re.sub(r"\[(\d{10,})\]", sub, result)
        return result
