"""Parser for Eclipse BIRT report design files (.rptdesign)."""

from __future__ import annotations

import logging
from pathlib import Path
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

# BIRT uses a default namespace in its XML
_BIRT_NS = "http://www.eclipse.org/birt/2005/design"


def _ns(tag: str) -> str:
    """Wrap a tag name in the BIRT namespace."""
    return f"{{{_BIRT_NS}}}{tag}"


def _find_text(element: ET.Element, tag: str) -> str:
    """Return the text of a direct child element, or empty string."""
    child = element.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _prop_value(element: ET.Element, name: str) -> str:
    """Return text of <property name='{name}'> child, or empty string."""
    for prop in element.findall(_ns("property")):
        if prop.get("name") == name:
            return (prop.text or "").strip()
    return ""


def _xml_prop_value(element: ET.Element, name: str) -> str:
    """Return text of <xml-property name='{name}'> child, or empty string."""
    for prop in element.findall(_ns("xml-property")):
        if prop.get("name") == name:
            return (prop.text or "").strip()
    return ""


class BirtParser(BaseParser):
    """Parser for Eclipse BIRT .rptdesign files.

    BIRT report design files are XML documents following the Eclipse BIRT
    schema. This parser extracts data sources, data sets (with fields and
    SQL queries), parameters, and report body elements.
    """

    extensions: list[str] = [".rptdesign"]
    tool: str = "BIRT"

    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a BIRT .rptdesign file and return normalized metadata."""
        source = str(file_path)
        result = ExtractionResult(
            source_file=source,
            file_type=".rptdesign",
            tool_name=self.tool,
        )

        try:
            tree = ET.parse(file_path)  # noqa: S314  (trusted internal files)
        except ET.ParseError as exc:
            msg = f"XML parse error in {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result
        except OSError as exc:
            msg = f"Cannot open {source}: {exc}"
            logger.error(msg)
            result.errors.append(msg)
            return result

        root = tree.getroot()

        # Strip namespace from root tag for robust matching; also support
        # files that omit the namespace declaration.
        ns_prefix = f"{{{_BIRT_NS}}}"
        use_ns = root.tag.startswith(ns_prefix)

        def tag(name: str) -> str:
            return _ns(name) if use_ns else name

        try:
            result.datasources = self._extract_datasources(root, tag)
            ds_fields, sql_map = self._extract_datasets(root, tag)
            result.fields = ds_fields
            result.parameters = self._extract_parameters(root, tag)
            result.report_elements = self._extract_body_elements(root, tag)

            # Store SQL queries in metadata keyed by dataset name
            if sql_map:
                result.metadata["sql_queries"] = sql_map

        except Exception as exc:  # noqa: BLE001
            msg = f"Unexpected error parsing {source}: {exc}"
            logger.exception(msg)
            result.errors.append(msg)

        return result

    # ------------------------------------------------------------------
    # Private extraction helpers
    # ------------------------------------------------------------------

    def _extract_datasources(
        self, root: ET.Element, tag: "function"
    ) -> list[DataSource]:
        """Extract <oda-data-source> elements from <data-sources>."""
        datasources: list[DataSource] = []
        data_sources_el = root.find(tag("data-sources"))
        if data_sources_el is None:
            return datasources

        for ds_el in data_sources_el.findall(tag("oda-data-source")):
            name = ds_el.get("name", "")
            extension_id = ds_el.get("extensionID", "")

            # Connection string is usually in a <property name="URL"> or
            # similar nested child; collect all properties for flexibility.
            conn_string = (
                _prop_value(ds_el, "odaURL")
                or _prop_value(ds_el, "URL")
                or _prop_value(ds_el, "url")
                or _prop_value(ds_el, "connectionString")
            )
            database = _prop_value(ds_el, "odaDatabase") or _prop_value(ds_el, "database")

            datasources.append(
                DataSource(
                    name=name,
                    connection_type=extension_id,
                    connection_string=conn_string,
                    database=database,
                )
            )
            logger.debug("BIRT: found data source '%s' (%s)", name, extension_id)

        return datasources

    def _extract_datasets(
        self, root: ET.Element, tag: "function"
    ) -> tuple[list[Field], dict[str, str]]:
        """Extract fields from <oda-data-set> result set columns and SQL queries."""
        fields: list[Field] = []
        sql_map: dict[str, str] = {}

        data_sets_el = root.find(tag("data-sets"))
        if data_sets_el is None:
            return fields, sql_map

        for ds_el in data_sets_el.findall(tag("oda-data-set")):
            dataset_name = ds_el.get("name", "")

            # SQL query text
            query_text = _xml_prop_value(ds_el, "queryText")
            if query_text:
                sql_map[dataset_name] = query_text
                logger.debug("BIRT: found SQL for dataset '%s'", dataset_name)

            # Result set columns live inside:
            # <structure name="cachedMetaData">
            #   <list-property name="resultSetColumns">
            #     <structure> ... </structure>
            #   </list-property>
            # </structure>
            # OR directly under:
            # <list-property name="resultSetColumns">
            #   <structure> ... </structure>
            # </list-property>
            for list_prop in ds_el.iter(tag("list-property")):
                if list_prop.get("name") != "resultSetColumns":
                    continue
                for struct in list_prop.findall(tag("structure")):
                    col_name = _prop_value(struct, "name")
                    col_type = _prop_value(struct, "dataType")
                    if col_name:
                        # Infer role from BIRT data types
                        role = ""
                        if col_type:
                            lower_type = col_type.lower()
                            if lower_type in (
                                "integer", "float", "double", "decimal",
                                "bigdecimal", "long", "short",
                            ):
                                role = "measure"
                            else:
                                role = "dimension"
                        fields.append(
                            Field(
                                name=col_name,
                                data_type=col_type,
                                field_type="column",
                                role=role,
                                datasource=dataset_name,
                            )
                        )
                        logger.debug(
                            "BIRT: found field '%s' (%s) in dataset '%s'",
                            col_name,
                            col_type,
                            dataset_name,
                        )

        return fields, sql_map

    def _extract_parameters(
        self, root: ET.Element, tag: "function"
    ) -> list[Parameter]:
        """Extract <scalar-parameter> elements from <parameters>."""
        parameters: list[Parameter] = []
        params_el = root.find(tag("parameters"))
        if params_el is None:
            return parameters

        for param_el in params_el.findall(tag("scalar-parameter")):
            name = param_el.get("name", "")
            data_type = _prop_value(param_el, "dataType")
            default_value = _prop_value(param_el, "defaultValue")
            prompt_text = _prop_value(param_el, "promptText")

            parameters.append(
                Parameter(
                    name=name,
                    data_type=data_type,
                    default_value=default_value,
                    prompt_text=prompt_text,
                )
            )
            logger.debug("BIRT: found parameter '%s'", name)

        return parameters

    def _extract_body_elements(
        self, root: ET.Element, tag: "function"
    ) -> list[ReportElement]:
        """Extract top-level elements from <body> (grids, tables, charts, labels)."""
        elements: list[ReportElement] = []
        body_el = root.find(tag("body"))
        if body_el is None:
            return elements

        for child in body_el:
            # Strip namespace to get the local tag name as element_type
            raw_tag = child.tag
            if raw_tag.startswith("{"):
                local = raw_tag.split("}", 1)[1]
            else:
                local = raw_tag

            name = child.get("name", "") or child.get("id", local)
            elements.append(ReportElement(name=name, element_type=local))
            logger.debug("BIRT: found body element '%s' (%s)", name, local)

        return elements
