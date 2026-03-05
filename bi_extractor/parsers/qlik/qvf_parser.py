"""Parser for Qlik Sense application files (.qvf).

QVF files are SQLite databases containing the application definition,
data model metadata, load script, sheets, and visualization definitions.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, ClassVar

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
    Filter,
    ReportElement,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)


class QvfParser(BaseParser):
    """Parse Qlik Sense .qvf application files into the universal model."""

    extensions: ClassVar[list[str]] = [".qvf"]
    tool: ClassVar[str] = "Qlik Sense"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a Qlik Sense application file.

        Never raises — all errors are captured in ExtractionResult.errors.
        """
        result = ExtractionResult(
            source_file=str(file_path),
            file_type=file_path.suffix.lower().lstrip("."),
            tool_name=self.tool,
        )

        try:
            self._extract(file_path, result)
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to parse {file_path}: {exc}"
            logger.error(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract(self, file_path: Path, result: ExtractionResult) -> None:
        """Open the SQLite database and populate result in-place."""
        uri = f"file:{file_path.as_posix()}?mode=ro"
        try:
            conn = sqlite3.connect(uri, uri=True)
        except sqlite3.OperationalError as exc:
            result.errors.append(f"Cannot open as SQLite database: {exc}")
            return

        try:
            tables = self._discover_tables(conn)
            logger.debug("QVF tables found: %s", tables)

            if not tables:
                logger.info("No tables found in %s", file_path)
                return

            self._extract_datasources(conn, tables, result)
            self._extract_fields(conn, tables, result)
            self._extract_objects(conn, tables, result)
            self._extract_load_script(conn, tables, result)
        finally:
            conn.close()

    def _discover_tables(self, conn: sqlite3.Connection) -> set[str]:
        """Return the set of table names present in the database."""
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        return {row[0] for row in cursor.fetchall()}

    def _extract_datasources(
        self, conn: sqlite3.Connection, tables: set[str], result: ExtractionResult
    ) -> None:
        """Populate result.datasources from qlik_tables."""
        if "qlik_tables" not in tables:
            return

        try:
            cursor = conn.execute("SELECT name, source, fields FROM qlik_tables")
            for name, source, fields_csv in cursor.fetchall():
                field_list: list[str] = []
                if fields_csv:
                    field_list = [f.strip() for f in fields_csv.split(",") if f.strip()]
                result.datasources.append(
                    DataSource(
                        name=name or "",
                        connection_string=source or "",
                        connection_type=self._infer_connection_type(source or ""),
                        tables=field_list,
                    )
                )
        except sqlite3.Error as exc:
            msg = f"Error reading qlik_tables: {exc}"
            logger.warning(msg)
            result.errors.append(msg)

    def _infer_connection_type(self, source: str) -> str:
        """Guess connection type from the source path string."""
        lower = source.lower()
        if lower.endswith(".csv"):
            return "CSV"
        if lower.endswith((".xlsx", ".xls")):
            return "Excel"
        if lower.endswith(".qvd"):
            return "QVD"
        if "lib://" in lower:
            return "DataFiles"
        return ""

    def _extract_fields(
        self, conn: sqlite3.Connection, tables: set[str], result: ExtractionResult
    ) -> None:
        """Populate result.fields from qlik_fields."""
        if "qlik_fields" not in tables:
            return

        try:
            cursor = conn.execute(
                "SELECT name, src_table, data_type, tags FROM qlik_fields"
            )
            for name, src_table, data_type, tags in cursor.fetchall():
                result.fields.append(
                    Field(
                        name=name or "",
                        data_type=data_type or "",
                        datasource=src_table or "",
                        role=self._role_from_tags(tags or ""),
                    )
                )
        except sqlite3.Error as exc:
            msg = f"Error reading qlik_fields: {exc}"
            logger.warning(msg)
            result.errors.append(msg)

    def _role_from_tags(self, tags: str) -> str:
        """Derive a field role from Qlik tag string."""
        if "$key" in tags:
            return "key"
        if "$numeric" in tags or "$money" in tags:
            return "measure"
        if "$text" in tags:
            return "dimension"
        return ""

    def _extract_objects(
        self, conn: sqlite3.Connection, tables: set[str], result: ExtractionResult
    ) -> None:
        """Populate sheets (ReportElements), filters, and measure fields from qlik_objects."""
        if "qlik_objects" not in tables:
            return

        try:
            cursor = conn.execute("SELECT id, type, data FROM qlik_objects")
            for obj_id, obj_type, data_raw in cursor.fetchall():
                data: dict[str, Any] = {}
                if data_raw:
                    try:
                        data = json.loads(data_raw)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON in object %s", obj_id)

                obj_type_lower = (obj_type or "").lower()

                if obj_type_lower == "sheet":
                    self._handle_sheet(obj_id, data, result)
                elif obj_type_lower == "measure":
                    self._handle_measure(obj_id, data, result)
                elif obj_type_lower == "dimension":
                    self._handle_dimension(obj_id, data, result)
                elif "filter" in obj_type_lower or "bookmark" in obj_type_lower:
                    self._handle_filter(obj_id, obj_type, data, result)

        except sqlite3.Error as exc:
            msg = f"Error reading qlik_objects: {exc}"
            logger.warning(msg)
            result.errors.append(msg)

    def _handle_sheet(
        self, obj_id: str, data: dict[str, Any], result: ExtractionResult
    ) -> None:
        """Create a ReportElement for a sheet object."""
        title = data.get("title", obj_id)
        fields_used: list[str] = data.get("fields_used", [])
        result.report_elements.append(
            ReportElement(
                name=title,
                element_type="sheet",
                fields_used=list(fields_used),
            )
        )

    def _handle_measure(
        self, obj_id: str, data: dict[str, Any], result: ExtractionResult
    ) -> None:
        """Create a Field for a measure object."""
        title = data.get("title", obj_id)
        expression = data.get("expression", "")
        label = data.get("label", "")
        result.fields.append(
            Field(
                name=title,
                alias=label,
                formula=expression,
                field_type="measure",
                role="measure",
            )
        )

    def _handle_dimension(
        self, obj_id: str, data: dict[str, Any], result: ExtractionResult
    ) -> None:
        """Create a Field for a dimension object."""
        title = data.get("title", obj_id)
        field_ref = data.get("field", "")
        label = data.get("label", "")
        result.fields.append(
            Field(
                name=title,
                alias=label,
                field_type="dimension",
                role="dimension",
                datasource=field_ref,
            )
        )

    def _handle_filter(
        self, obj_id: str, obj_type: str, data: dict[str, Any], result: ExtractionResult
    ) -> None:
        """Create a Filter for a filter/bookmark object."""
        title = data.get("title", obj_id)
        normalized_type = "bookmark" if "bookmark" in (obj_type or "").lower() else "filter"
        result.filters.append(
            Filter(
                name=title,
                filter_type=normalized_type,
                expression=data.get("expression", ""),
            )
        )

    def _extract_load_script(
        self, conn: sqlite3.Connection, tables: set[str], result: ExtractionResult
    ) -> None:
        """Store the load script in result.metadata if available."""
        if "qlik_load_script" not in tables:
            return

        try:
            cursor = conn.execute("SELECT script FROM qlik_load_script LIMIT 1")
            row = cursor.fetchone()
            if row and row[0]:
                result.metadata["load_script"] = row[0]
        except sqlite3.Error as exc:
            msg = f"Error reading qlik_load_script: {exc}"
            logger.warning(msg)
            result.errors.append(msg)
