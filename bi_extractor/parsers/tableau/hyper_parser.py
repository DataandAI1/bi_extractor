"""Parser for Tableau Hyper extract files (.hyper).

Hyper files are Tableau's high-performance data extract format. Parsing
requires the optional ``tableauhyperapi`` package from Tableau.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from bi_extractor.core.models import (
    DataSource,
    ExtractionResult,
    Field,
)
from bi_extractor.parsers.base import BaseParser

logger = logging.getLogger(__name__)

# Tableau Hyper SQL type name to normalized type mapping
_HYPER_TYPE_MAP: dict[str, str] = {
    "BOOLEAN": "boolean",
    "SMALL_INT": "integer",
    "INTEGER": "integer",
    "BIG_INT": "integer",
    "NUMERIC": "decimal",
    "DOUBLE": "float",
    "OID": "integer",
    "BYTES": "binary",
    "TEXT": "string",
    "VARCHAR": "string",
    "CHAR": "string",
    "JSON": "string",
    "DATE": "date",
    "INTERVAL": "interval",
    "TIME": "time",
    "TIMESTAMP": "timestamp",
    "TIMESTAMP_TZ": "timestamp",
    "GEOGRAPHY": "geography",
}


def _normalize_hyper_type(type_tag: object) -> str:
    """Normalize a Hyper SqlType tag to a simple type string."""
    type_name = str(type_tag).upper().replace("SQLTYPE.", "").replace("<", "").replace(">", "").strip()
    # Handle parameterized types like "VARCHAR(100)"
    base = type_name.split("(")[0].strip()
    return _HYPER_TYPE_MAP.get(base, type_name.lower())


class HyperParser(BaseParser):
    """Parse Tableau Hyper extract files (.hyper) into the universal model.

    Requires the optional ``tableauhyperapi`` package. If missing, parse()
    returns an error result with an install hint.
    """

    extensions: ClassVar[list[str]] = [".hyper"]
    tool: ClassVar[str] = "Tableau"

    # ------------------------------------------------------------------
    # Dependency check
    # ------------------------------------------------------------------

    def check_dependencies(self) -> tuple[bool, str]:
        """Return (False, install hint) when tableauhyperapi is not installed."""
        try:
            self._import_hyper_api()
            return True, "tableauhyperapi is available"
        except ImportError:
            return False, "pip install tableauhyperapi"

    # ------------------------------------------------------------------
    # Mockable import helper
    # ------------------------------------------------------------------

    def _import_hyper_api(self):  # type: ignore[return]
        """Import tableauhyperapi and return the module.

        Isolated into its own method so tests can patch it easily.
        Raises ImportError when the package is not installed.
        """
        import tableauhyperapi
        return tableauhyperapi

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a Tableau Hyper extract file.

        Never raises — all errors are captured in ExtractionResult.errors.
        """
        file_type = file_path.suffix.lower().lstrip(".")

        result = ExtractionResult(
            source_file=str(file_path),
            file_type=file_type,
            tool_name=self.tool,
        )

        # Check dependency first
        try:
            hyper_api = self._import_hyper_api()
        except ImportError:
            msg = (
                "tableauhyperapi is not installed. "
                "Install it with: pip install tableauhyperapi"
            )
            logger.error(msg)
            result.errors.append(msg)
            return result

        # File existence check
        if not file_path.exists():
            msg = f"File not found: {file_path}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        try:
            self._extract(file_path, hyper_api, result)
        except Exception as exc:  # noqa: BLE001
            msg = f"Failed to parse {file_path.name}: {exc}"
            logger.error(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # Private extraction logic
    # ------------------------------------------------------------------

    def _extract(self, file_path: Path, hyper_api: object, result: ExtractionResult) -> None:
        """Open the Hyper file and populate *result* in-place."""
        HyperProcess = hyper_api.HyperProcess  # type: ignore[attr-defined]
        Connection = hyper_api.Connection  # type: ignore[attr-defined]
        Telemetry = hyper_api.Telemetry  # type: ignore[attr-defined]

        schema_count = 0
        table_count = 0
        column_count = 0

        with HyperProcess(telemetry=Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU) as hyper:
            with Connection(endpoint=hyper.endpoint, database=file_path) as connection:
                catalog = connection.catalog
                schema_names = catalog.get_schema_names()

                for schema in schema_names:
                    schema_name: str = schema.name.unescaped
                    schema_count += 1

                    table_names = catalog.get_table_names(schema)
                    table_name_strings: list[str] = []

                    for table in table_names:
                        table_display: str = table.name.unescaped
                        table_name_strings.append(table_display)
                        table_count += 1

                        table_def = catalog.get_table_definition(table)
                        for col in table_def.columns:
                            col_name: str = col.name.unescaped
                            col_type_normalized = _normalize_hyper_type(col.type.tag)
                            column_count += 1

                            result.fields.append(
                                Field(
                                    name=col_name,
                                    data_type=col_type_normalized,
                                    datasource=f"{schema_name}.{table_display}",
                                )
                            )

                    result.datasources.append(
                        DataSource(
                            name=schema_name,
                            tables=table_name_strings,
                        )
                    )

        result.metadata.update(
            {
                "schema_count": schema_count,
                "table_count": table_count,
                "column_count": column_count,
            }
        )

        logger.info(
            "Parsed %s: %d schema(s), %d table(s), %d column(s)",
            file_path.name,
            schema_count,
            table_count,
            column_count,
        )
