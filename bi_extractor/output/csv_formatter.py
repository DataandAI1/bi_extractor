"""CSV output formatter.

Produces a CSV file compatible with the original tableau_metadata_extractor.py
output format. The to_flat_rows() logic lives here (not on ExtractionResult)
because Column ID assignment spans multiple files.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from bi_extractor.core.models import ExtractionResult

logger = logging.getLogger(__name__)

# Original 14 columns from the Tableau extractor, preserved for backward compat.
# New columns are appended after these.
LEGACY_COLUMNS = [
    "Column ID",
    "Column Name",
    "Column Alias",
    "Field Type",
    "Connection Name",
    "Connection Alias",
    "datatype",
    "role",
    "Calculation Formula",
    "Original Calculation",
    "Calc Clean Status",
    "Field Used in Worksheets",
    "Worksheet Name",
    "File Name",
]

# Extended columns added by the universal extractor
EXTENDED_COLUMNS = [
    "Tool",
    "File Type",
    "Parameter Count",
    "Relationship Count",
    "Extraction Errors",
]

ALL_COLUMNS = LEGACY_COLUMNS + EXTENDED_COLUMNS


def to_flat_rows(results: list[ExtractionResult]) -> list[dict[str, str]]:
    """Flatten extraction results into CSV-ready row dicts.

    Produces one row per field-per-worksheet combination (matching the
    original Tableau extractor output format). Column IDs are assigned
    sequentially across ALL files.
    """
    rows: list[dict[str, str]] = []
    column_id = 1

    for result in results:
        # Build connection lookup from datasources
        connections: dict[str, tuple[str, str]] = {}
        for ds in result.datasources:
            connections[ds.name] = (
                ds.connection_string or ds.name,
                ds.alias or ds.name,
            )

        # Build worksheet usage lookup: field_name -> list of worksheet names
        field_worksheets: dict[str, list[str]] = {}
        for element in result.report_elements:
            for field_name in element.fields_used:
                field_worksheets.setdefault(field_name, []).append(element.name)

        for field in result.fields:
            worksheets = field_worksheets.get(field.name, [])
            conn_name, conn_alias = connections.get(
                field.datasource, (field.datasource, field.datasource)
            )

            if worksheets:
                for ws_name in worksheets:
                    rows.append(
                        _make_row(
                            column_id,
                            field,
                            conn_name,
                            conn_alias,
                            used_in_ws="Yes",
                            ws_name=ws_name,
                            result=result,
                        )
                    )
                    column_id += 1
            else:
                rows.append(
                    _make_row(
                        column_id,
                        field,
                        conn_name,
                        conn_alias,
                        used_in_ws="No",
                        ws_name="",
                        result=result,
                    )
                )
                column_id += 1

    return rows


def _make_row(
    column_id: int,
    field: object,
    conn_name: str,
    conn_alias: str,
    used_in_ws: str,
    ws_name: str,
    result: ExtractionResult,
) -> dict[str, str]:
    """Create a single CSV row dict."""
    from bi_extractor.core.models import Field

    f: Field = field  # type: ignore[assignment]
    return {
        "Column ID": str(column_id),
        "Column Name": f.name,
        "Column Alias": f.alias,
        "Field Type": f.field_type,
        "Connection Name": conn_name,
        "Connection Alias": conn_alias,
        "datatype": f.data_type,
        "role": f.role,
        "Calculation Formula": f.formula,
        "Original Calculation": f.original_formula,
        "Calc Clean Status": f.formula_status,
        "Field Used in Worksheets": used_in_ws,
        "Worksheet Name": ws_name,
        "File Name": Path(result.source_file).name,
        "Tool": result.tool_name,
        "File Type": result.file_type,
        "Parameter Count": str(len(result.parameters)),
        "Relationship Count": str(len(result.relationships)),
        "Extraction Errors": "; ".join(result.errors) if result.errors else "",
    }


class CsvFormatter:
    """CSV output formatter."""

    def format_name(self) -> str:
        return "csv"

    def write(
        self,
        results: list[ExtractionResult],
        output_path: Path,
        filename: str = "BI_Metadata.csv",
    ) -> Path:
        """Write extraction results as a CSV file.

        Args:
            results: List of extraction results.
            output_path: Directory to write into.
            filename: Output filename (default: bi_metadata.csv).

        Returns:
            Path to the written CSV file.
        """
        rows = to_flat_rows(results)

        if not rows:
            logger.warning("No data to write")
            output_file = output_path / filename
            output_file.write_text("", encoding="utf-8")
            return output_file

        output_file = output_path / filename
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=ALL_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        logger.info("Wrote %d rows to %s", len(rows), output_file)
        return output_file
