"""Tableau TWB/TWBX parser — maps Tableau workbook metadata to the universal model."""

from __future__ import annotations

import logging
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import ClassVar

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
    ReportElement,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class TableauTwbParser(BaseParser):
    """Parse Tableau .twb and .twbx workbook files into the universal model."""

    extensions: ClassVar[list[str]] = [".twb", ".twbx"]
    tool: ClassVar[str] = "Tableau"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a Tableau workbook file.

        Never raises — all errors are captured in ExtractionResult.errors.
        """
        result = ExtractionResult(
            source_file=str(file_path),
            file_type=file_path.suffix.lower().lstrip("."),
            tool_name=self.tool,
        )

        try:
            tree, filename = self._extract_tree(file_path)
            root = tree.getroot()
            logger.info("Parsing %s", filename)
            self._populate_result(root, filename, result)
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to parse {file_path}: {exc}"
            logger.error(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_tree(self, file_path: Path) -> tuple[ET.ElementTree, str]:
        """Return the parsed ElementTree and the base filename.

        Handles both .twb (plain XML) and .twbx (ZIP archive containing a .twb).
        """
        if file_path.suffix.lower() == ".twbx":
            with zipfile.ZipFile(file_path, "r") as zf:
                twb_name = next(
                    n for n in zf.namelist() if n.lower().endswith(".twb")
                )
                with zf.open(twb_name) as f:
                    return ET.parse(f), file_path.name
        return ET.parse(file_path), file_path.name

    def _clean_formula(
        self, raw_formula: str, calc_map: dict[str, str]
    ) -> tuple[str, str]:
        """Replace calculation IDs in a formula with human-readable names.

        Returns (cleaned_formula, status_string).
        """
        if not raw_formula:
            return raw_formula, "No Formula"

        cleaned = raw_formula
        status = "Success"
        replacements_made = 0

        try:
            # Pattern 1: [Calculation_1234567890123] format
            calc_pattern = r"\[Calculation_(\d+)\]"

            def replace_calc_id(match: re.Match) -> str:
                nonlocal replacements_made
                calc_id = match.group(1)
                if calc_id in calc_map:
                    replacements_made += 1
                    return f"[{calc_map[calc_id]}]"
                return match.group(0)

            cleaned = re.sub(calc_pattern, replace_calc_id, cleaned)

            # Pattern 2: @{id} style references
            at_pattern = r"@\{(\d+)\}"

            def replace_at_id(match: re.Match) -> str:
                nonlocal replacements_made
                calc_id = match.group(1)
                if calc_id in calc_map:
                    replacements_made += 1
                    return f"[{calc_map[calc_id]}]"
                return match.group(0)

            cleaned = re.sub(at_pattern, replace_at_id, cleaned)

            # Pattern 3: Direct long numeric references [1234567890123]
            direct_id_pattern = r"\[(\d{10,})\]"

            def replace_direct_id(match: re.Match) -> str:
                nonlocal replacements_made
                calc_id = match.group(1)
                if calc_id in calc_map:
                    replacements_made += 1
                    return f"[{calc_map[calc_id]}]"
                return match.group(0)

            cleaned = re.sub(direct_id_pattern, replace_direct_id, cleaned)

            # Determine resolution status
            unresolved_pattern = r"\[Calculation_\d+\]|\[\d{10,}\]|@\{\d+\}"
            if replacements_made == 0 and re.search(unresolved_pattern, raw_formula):
                status = "Unresolved References"
            elif replacements_made > 0 and re.search(unresolved_pattern, cleaned):
                status = "Partially Resolved"

        except Exception as exc:  # noqa: BLE001
            status = f"Error: {exc}"
            cleaned = raw_formula

        return cleaned, status

    def _populate_result(
        self, root: ET.Element, filename: str, result: ExtractionResult
    ) -> None:
        """Drive the full extraction and populate *result* in-place."""
        # Step 1: Build calculation ID → caption map (two-pass to catch all IDs)
        calc_map = self._build_calc_map(root)

        # Step 2: Extract datasources and fields
        raw_fields: list[dict] = []
        raw_connections: dict[str, dict] = {}
        self._extract_datasources(root, raw_fields, raw_connections, calc_map)

        # Step 3: Standalone calculations not already captured
        self._extract_standalone_calculations(root, raw_fields)

        # Step 4: Worksheet usage
        raw_usage = self._extract_worksheet_usage(root)

        # Step 5: Map raw dicts to universal model
        self._map_to_model(
            raw_fields, raw_connections, raw_usage, calc_map, result
        )

    def _build_calc_map(self, root: ET.Element) -> dict[str, str]:
        """Build a mapping from calculation numeric IDs to human-readable names."""
        calc_map: dict[str, str] = {}

        # From column elements that contain a calculation child
        for col in root.findall(".//column"):
            calc_elem = col.find(".//calculation")
            if calc_elem is not None:
                calc_id = calc_elem.get("id", "")
                if calc_id:
                    caption = col.get("caption", col.get("name", ""))
                    if caption:
                        calc_map[calc_id] = caption

        # From standalone calculation elements
        for calc in root.findall(".//calculation"):
            calc_id = calc.get("id", "")
            if calc_id:
                caption = calc.get("caption", calc.get("name", ""))
                if caption:
                    calc_map[calc_id] = caption

        return calc_map

    def _extract_datasources(
        self,
        root: ET.Element,
        raw_fields: list[dict],
        raw_connections: dict[str, dict],
        calc_map: dict[str, str],
    ) -> None:
        """Extract datasource connections and their columns into raw dicts."""
        for ds in root.findall(".//datasource"):
            ds_name = ds.get("name", "")
            ds_caption = ds.get("caption", ds_name)

            conn = ds.find(".//connection")
            if conn is not None:
                conn_class = conn.get("class", "")
                conn_name = conn.get(
                    "server",
                    conn.get("filename", conn.get("database", "")),
                )
                raw_connections[ds_name] = {
                    "name": conn_name,
                    "alias": ds_caption,
                    "class": conn_class,
                }

            for col in ds.findall(".//column"):
                field_name = col.get("name", "")
                field_caption = col.get("caption", field_name)

                calc_elem = col.find(".//calculation")
                formula = ""
                field_type = "Dimension"

                if calc_elem is not None:
                    formula = calc_elem.get("formula", "")
                    field_type = "Calculated Field"
                    calc_class = calc_elem.get("class", "")
                    if "tableau" in calc_class:
                        field_type = "Table Calculation"

                    # Update calc_map with any new IDs found here
                    calc_id = calc_elem.get("id", "")
                    if calc_id and field_caption:
                        calc_map[calc_id] = field_caption

                elif col.get("role") == "measure":
                    field_type = "Measure"
                    if col.get("aggregation"):
                        field_type = "Aggregated Measure"

                raw_fields.append(
                    {
                        "name": field_name,
                        "caption": field_caption,
                        "datatype": col.get("datatype", ""),
                        "role": col.get("role", ""),
                        "datasource": ds_name,
                        "formula": formula,
                        "field_type": field_type,
                    }
                )

    def _extract_standalone_calculations(
        self, root: ET.Element, raw_fields: list[dict]
    ) -> None:
        """Add standalone calculation elements not already captured via columns."""
        existing_names = {f["name"] for f in raw_fields}
        for calc in root.findall(".//calculation"):
            calc_name = calc.get("name", "")
            if calc_name and calc_name not in existing_names:
                raw_fields.append(
                    {
                        "name": calc_name,
                        "caption": calc.get("caption", calc_name),
                        "datatype": calc.get("datatype", ""),
                        "role": calc.get("role", ""),
                        "datasource": "",
                        "formula": calc.get("formula", ""),
                        "field_type": "Calculated Field",
                    }
                )
                existing_names.add(calc_name)

    def _extract_worksheet_usage(
        self, root: ET.Element
    ) -> list[dict]:
        """Return deduplicated list of {field, worksheet, datasource} usages."""
        usages: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for ws in root.findall(".//worksheet"):
            ws_name = ws.get("name", "")

            for dep in ws.findall(".//datasource-dependencies"):
                ds_name = dep.get("datasource", "")
                for col in dep.findall(".//column"):
                    field_name = col.get("name", "")
                    if field_name:
                        key = (field_name, ws_name)
                        if key not in seen:
                            seen.add(key)
                            usages.append(
                                {
                                    "field": field_name,
                                    "worksheet": ws_name,
                                    "datasource": ds_name,
                                }
                            )

            for enc_col in ws.findall(".//encoding//column"):
                field_ref = enc_col.text or enc_col.get("column", "")
                if field_ref:
                    if field_ref.startswith("[") and field_ref.endswith("]"):
                        field_ref = field_ref[1:-1]
                    key = (field_ref, ws_name)
                    if key not in seen:
                        seen.add(key)
                        usages.append(
                            {
                                "field": field_ref,
                                "worksheet": ws_name,
                                "datasource": "",
                            }
                        )

        return usages

    def _map_to_model(
        self,
        raw_fields: list[dict],
        raw_connections: dict[str, dict],
        raw_usage: list[dict],
        calc_map: dict[str, str],
        result: ExtractionResult,
    ) -> None:
        """Convert raw extraction dicts to universal model instances."""
        # DataSource objects
        for ds_name, conn_info in raw_connections.items():
            result.datasources.append(
                DataSource(
                    name=ds_name,
                    alias=conn_info.get("alias", ds_name),
                    connection_type=conn_info.get("class", ""),
                    connection_string=conn_info.get("name", ""),
                )
            )

        # Field objects (with formula cleaning)
        for raw in raw_fields:
            original_formula = raw.get("formula", "")
            if original_formula:
                cleaned_formula, formula_status = self._clean_formula(
                    original_formula, calc_map
                )
            else:
                cleaned_formula = ""
                formula_status = "No Calculation"

            result.fields.append(
                Field(
                    name=raw["name"],
                    alias=raw.get("caption", ""),
                    data_type=raw.get("datatype", ""),
                    role=raw.get("role", ""),
                    field_type=raw.get("field_type", ""),
                    formula=cleaned_formula,
                    original_formula=original_formula,
                    formula_status=formula_status,
                    datasource=raw.get("datasource", ""),
                )
            )

        # ReportElement objects (worksheets with the fields they use)
        worksheets: dict[str, ReportElement] = {}
        for usage in raw_usage:
            ws_name = usage["worksheet"]
            if ws_name not in worksheets:
                worksheets[ws_name] = ReportElement(
                    name=ws_name,
                    element_type="worksheet",
                )
            field_name = usage["field"]
            if field_name not in worksheets[ws_name].fields_used:
                worksheets[ws_name].fields_used.append(field_name)

        result.report_elements.extend(worksheets.values())
