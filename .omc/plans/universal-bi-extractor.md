# Universal BI Report Metadata Extractor -- Implementation Plan

**Created:** 2026-03-04
**Status:** APPROVED -- Consensus reached (Planner + Architect + Critic)
**Reviewed:** 2026-03-04
**Package Name:** bi_extractor (PyPI: bi-extractor, CLI: bi-extractor)
**Python Version:** 3.10+
**Complexity:** HIGH
**Estimated Scope:** ~40 new files, 4 phases, significant architectural change

---

## Context

The project is currently a single-file Python application (`tableau_metadata_extractor.py`, 513 lines) that extracts metadata from Tableau `.twb` and `.twbx` files using only Python stdlib. It outputs a 14-column CSV with fields, formulas, connections, and worksheet usage. There are no tests, no configuration, and no plugin architecture.

The goal is to transform this into a universal BI Report Metadata Extractor supporting 22+ file formats across Tableau, Power BI, SSRS, Crystal Reports, Qlik, JasperReports, BIRT, Oracle BI, SAP BusinessObjects, Pentaho, and MicroStrategy.

---

## Work Objectives

1. Refactor the monolithic single-file design into an extensible, plugin-based package architecture
2. Define a universal metadata model that normalizes output across all BI tools
3. Implement parsers for 22+ file formats grouped by parsing complexity
4. Add CLI support alongside the existing GUI
5. Expand output beyond CSV to include JSON and Excel
6. Establish a testing strategy that works even for proprietary binary formats

---

## Resolved Open Questions

| # | Question | Decision |
|---|----------|----------|
| 1 | Package name | `bi_extractor` (PyPI: `bi-extractor`, CLI: `bi-extractor`) |
| 2 | Python version floor | 3.10+ (enables `list[str]`, `X \| Y`, `match/case`, `slots=True`) |
| 3 | Backward compat strictness | Data-equivalent (same columns, same data, same row count -- not byte-for-byte) |
| 4 | Encrypted .pbix | Skip -- return clear error message, defer decryption |
| 5 | Crystal Reports versions | Best effort with latest available |
| 6 | Credential management | Env vars first, optional `.bi-extractor.toml` second |
| 7 | Monorepo vs packages | Single package with optional dependency groups |
| 8 | Data sanitization | Redact passwords only by default; `--sanitize=full` flag for full redaction |
| 9 | Limited support threshold | Include as stubs if they extract at least one real metadata field |
| 10 | GUI framework | Stay on tkinter (use `ttk` for modern look, no new deps) |

---

## Consensus Revisions (from Architect + Critic review)

### Critical Revisions Applied
1. **Mutable dataclasses** -- Use regular dataclasses (NOT frozen=True). Existing Tableau code accumulates data across 3 mutation passes. Use `slots=True` for performance.
2. **`to_flat_rows()` moved to CSV formatter** -- Column IDs span multiple files, so flattening logic belongs on the formatter that receives `list[ExtractionResult]`, not on individual results.
3. **Guarded import pattern prescribed** -- All parser modules must wrap optional dependency imports in `try/except` at module level. Auto-discovery catches `ImportError` per-module.
4. **Test infrastructure moved to Task 1.1b** -- pytest setup, conftest.py, and Tableau regression fixtures created immediately after package structure, BEFORE the Tableau refactor.
5. **All 10 open questions resolved** -- See table above.

### Non-Blocking Improvements Applied
- Flat `bi_extractor/` layout (no `src/` directory) -- simpler for internal tool
- `source_file` removed from child entities -- kept only on `ExtractionResult`
- `extensions` and `tool` are class-level `ClassVar` attributes, not abstract methods
- `parse()` signature accepts `Path` (not `str`)
- `logging` module replaces `print()` throughout
- `Filter` dataclass added to model for BI tools with rich filter semantics
- Risk register expanded with: Tableau refactor regression, GUI threading, cross-platform paths, row ordering

---

## Guardrails

### Must Have
- Backward compatibility: existing Tableau `.twb`/`.twbx` extraction must produce data-equivalent output after refactor
- Each parser must be independently testable with fixture files
- The architecture must allow adding a new parser without modifying core engine code
- All parsers must output through the same universal metadata model
- CLI must support all functionality available in the GUI
- Clean dependency separation: core engine uses stdlib only; parsers declare their own optional dependencies
- All optional imports guarded with try/except at module level (never bare top-level imports of optional deps)
- Use Python `logging` module -- no `print()` for progress/status

### Must NOT Have
- No breaking changes to the existing CSV output format (add columns, never remove or rename)
- No hard dependency on commercial/licensed SDKs in the core package (wrap them as optional parsers)
- No parser should crash the entire application -- graceful degradation with error reporting per file
- No monolithic "god class" -- keep parsers as focused, single-responsibility modules
- No frozen dataclasses -- use regular mutable dataclasses with `slots=True`

---

## Task Flow

```
Phase 1: Foundation          Phase 2: ZIP Parsers       Phase 3: Binary Parsers     Phase 4: Polish
(Architecture + XML)         (Power BI, Pentaho)        (Crystal, Qlik, SAP)        (API + Extras)
        |                           |                          |                         |
  [1.1]  Package structure    [2.1] PBIX/PBIT parser     [3.1] Crystal Reports     [4.1] MicroStrategy
  [1.1b] Test infrastructure  [2.2] Pentaho parser       [3.2] Qlik parsers             API extractor
  [1.2]  Universal model      [2.3] TDSX parser          [3.3] SAP BO parsers      [4.2] Qlik Sense
  [1.3]  Base parser ABC      [2.4] XDOZ parser          [3.4] Hyper/TDE parsers        API extractor
  [1.4]  Parser registry      [2.5] Output formatters    [3.5] Oracle RDF parser   [4.3] GUI overhaul
  [1.5]  Refactor Tableau            (JSON, Excel)       [3.6] Jasper compiled      [4.4] Documentation
  [1.6]  TDS parser                                                                      + packaging
  [1.7]  SSRS RDL/RDLC parser
  [1.8]  JasperReports parser
  [1.9]  BIRT parser
  [1.10] Oracle XDO parser
  [1.11] CLI interface
```

---

## Phase 1: Foundation (Architecture Refactor + XML Parsers + CLI)

This is the critical phase. Everything else depends on getting the architecture right.

### Task 1.1 -- Create Package Structure

Transform the single-file project into a proper Python package.

**Target directory layout (flat package -- no src/ directory):**

```
Tableau_Extractor/
|-- pyproject.toml                    # Project metadata, dependencies, entry points
|-- README.md
|-- LICENSE
|-- .gitignore
|
|-- bi_extractor/
|   |-- __init__.py                   # Package init, version
|   |
|   |-- core/
|   |   |-- __init__.py
|   |   |-- models.py                 # Universal metadata dataclasses (mutable, slots=True)
|   |   |-- registry.py               # Parser registry / factory with guarded auto-discovery
|   |   |-- engine.py                 # Orchestration: accept file list, route to parsers, collect results
|   |   |-- errors.py                 # Custom exception hierarchy
|   |
|   |-- parsers/
|   |   |-- __init__.py
|   |   |-- base.py                   # Abstract base parser (ClassVar extensions/tool, parse(Path))
|   |   |-- tableau/
|   |   |   |-- __init__.py
|   |   |   |-- twb_parser.py         # .twb / .twbx (refactored from current code)
|   |   |   |-- tds_parser.py         # .tds / .tdsx
|   |   |   |-- hyper_parser.py       # .hyper (Phase 3)
|   |   |   |-- tde_parser.py         # .tde (Phase 3)
|   |   |
|   |   |-- microsoft/
|   |   |   |-- __init__.py
|   |   |   |-- ssrs_parser.py        # .rdl / .rdlc
|   |   |   |-- pbix_parser.py        # .pbix / .pbit (Phase 2)
|   |   |
|   |   |-- jasper/
|   |   |   |-- __init__.py
|   |   |   |-- jrxml_parser.py       # .jrxml
|   |   |   |-- jasper_parser.py      # .jasper compiled (Phase 3)
|   |   |
|   |   |-- eclipse/
|   |   |   |-- __init__.py
|   |   |   |-- birt_parser.py        # .rptdesign
|   |   |
|   |   |-- oracle/
|   |   |   |-- __init__.py
|   |   |   |-- xdo_parser.py         # .xdo / .xdoz
|   |   |   |-- rdf_parser.py         # .rdf (Phase 3)
|   |   |
|   |   |-- sap/
|   |   |   |-- __init__.py
|   |   |   |-- crystal_parser.py     # .rpt / .rptr (Phase 3)
|   |   |   |-- bobj_parser.py        # .wid / .unv / .unx (Phase 3)
|   |   |
|   |   |-- qlik/
|   |   |   |-- __init__.py
|   |   |   |-- qvw_parser.py         # .qvw (Phase 3)
|   |   |   |-- qvf_parser.py         # .qvf (Phase 3/4)
|   |   |   |-- qvd_parser.py         # .qvd (Phase 3)
|   |   |
|   |   |-- pentaho/
|   |   |   |-- __init__.py
|   |   |   |-- prpt_parser.py        # .prpt (Phase 2)
|   |   |
|   |   |-- microstrategy/
|   |       |-- __init__.py
|   |       |-- mstr_parser.py        # .mstr (Phase 4)
|   |
|   |-- output/
|   |   |-- __init__.py
|   |   |-- base.py                   # Abstract output formatter
|   |   |-- csv_formatter.py          # CSV output (owns to_flat_rows + Column ID assignment)
|   |   |-- json_formatter.py         # JSON output (Phase 2)
|   |   |-- excel_formatter.py        # Excel output (Phase 2)
|   |
|   |-- cli/
|   |   |-- __init__.py
|   |   |-- main.py                   # argparse-based CLI entry point
|   |
|   |-- gui/
|       |-- __init__.py
|       |-- app.py                    # Refactored tkinter GUI (ttk themed, background thread)
|
|-- tests/
|   |-- __init__.py
|   |-- conftest.py                   # Shared fixtures
|   |-- fixtures/                     # Sample files for each format
|   |   |-- tableau/
|   |   |-- ssrs/
|   |   |-- jasper/
|   |   |-- birt/
|   |   |-- oracle/
|   |   |-- powerbi/
|   |   |-- pentaho/
|   |   |-- ...
|   |-- test_models.py
|   |-- test_registry.py
|   |-- test_engine.py
|   |-- test_tableau_parser.py
|   |-- test_ssrs_parser.py
|   |-- test_csv_formatter.py
|   |-- test_cli.py
|   |-- ...
|
|-- tableau_metadata_extractor.py     # KEPT as legacy entry point (thin wrapper)
```

**Acceptance criteria:**
- `pip install -e .` works from the project root
- `python tableau_metadata_extractor.py` still launches the GUI (backward compat)
- `bi-extractor` CLI entry point is registered via pyproject.toml
- All imports resolve without circular dependencies

---

### Task 1.1b -- Test Infrastructure (MOVED from Task 1.12)

Set up pytest immediately after package structure so the Tableau refactor (Task 1.5) has regression tests from day one.

**Setup:**
- `pyproject.toml` dev dependencies: `pytest`, `pytest-cov`, `mypy`
- `tests/conftest.py` with shared fixtures
- `tests/fixtures/tableau/` with at least one golden `.twb` file
- Generate golden CSV output from current `tableau_metadata_extractor.py` before any refactoring
- Regression test that compares refactored parser output against golden CSV (data-equivalent, not byte-for-byte)

**Acceptance criteria:**
- `pip install -e ".[dev]"` installs pytest and mypy
- `pytest` discovers and runs tests
- Golden CSV fixture is committed to repo before Task 1.5 begins
- Regression test framework is ready for the Tableau parser refactor

---

### Task 1.2 -- Define Universal Metadata Model

Create dataclasses in `bi_extractor/core/models.py` that normalize metadata across all BI tools.

**Core model structure (REVISED per consensus):**

```python
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

@dataclass(slots=True)
class DataSource:
    name: str
    alias: str = ""
    connection_type: str = ""     # e.g., "sqlserver", "postgres", "excel", "file"
    connection_string: str = ""   # Sanitized (no passwords)
    database: str = ""
    schema: str = ""
    tables: list[str] = field(default_factory=list)

@dataclass(slots=True)
class Field:
    name: str
    alias: str = ""               # Display name / caption
    data_type: str = ""           # Normalized: string, integer, float, date, datetime, boolean
    role: str = ""                # dimension, measure, attribute, unknown
    field_type: str = ""          # regular, calculated, parameter, aggregate, table_calculation
    formula: str = ""             # Cleaned formula (resolved references)
    original_formula: str = ""    # Raw formula as found in file
    formula_status: str = ""      # success, partial, unresolved, no_formula, error
    datasource: str = ""          # Reference to DataSource.name

    @property
    def dedup_key(self) -> tuple:
        """Hashable key for deduplication."""
        return (self.name, self.datasource)

@dataclass(slots=True)
class Filter:
    name: str
    filter_type: str = ""         # include, exclude, range, top_n, relative_date
    scope: str = ""               # visual, page, report, datasource
    field: str = ""               # Field reference
    expression: str = ""          # Filter expression or value list

@dataclass(slots=True)
class ReportElement:
    name: str
    element_type: str = ""        # worksheet, page, tab, section, subreport, group
    fields_used: list[str] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)

    @property
    def dedup_key(self) -> tuple:
        """Hashable key for deduplication."""
        return (self.name, self.element_type)

@dataclass(slots=True)
class Parameter:
    name: str
    alias: str = ""
    data_type: str = ""
    default_value: str = ""
    allowed_values: list[str] = field(default_factory=list)
    prompt_text: str = ""

@dataclass(slots=True)
class Relationship:
    left_table: str
    right_table: str
    join_type: str = ""           # inner, left, right, full, cross
    left_fields: list[str] = field(default_factory=list)
    right_fields: list[str] = field(default_factory=list)
    datasource: str = ""

@dataclass(slots=True)
class ExtractionResult:
    source_file: str              # ONLY place source_file lives -- child entities inherit from here
    file_type: str                # twb, pbix, rdl, etc.
    tool_name: str                # Tableau, Power BI, SSRS, etc.
    datasources: list[DataSource] = field(default_factory=list)
    fields: list[Field] = field(default_factory=list)
    report_elements: list[ReportElement] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)  # Tool-specific extras; keys documented per parser
```

**Key design notes:**
- `source_file` lives ONLY on `ExtractionResult` -- child entities do not carry it (prevents sync bugs)
- `to_flat_rows()` does NOT live here -- it belongs on the CSV formatter which receives `list[ExtractionResult]` and assigns cross-file sequential Column IDs
- `metadata: dict[str, Any]` is typed explicitly; each parser must document its metadata keys in its module docstring
- `Filter` is a first-class entity (not `list[str]`) to capture filter type, scope, field, and expression
- `dedup_key` properties on Field and ReportElement provide hashable keys for deduplication without requiring `__hash__`

**Acceptance criteria:**
- All dataclasses use `slots=True` for performance (NOT frozen=True -- parsers need mutation)
- Each dataclass has a `from_dict()` classmethod for easy construction from parser output
- Type hints are complete and pass mypy strict mode
- Lists preserve insertion order for deterministic output

---

### Task 1.3 -- Create Abstract Base Parser

Define the parser contract in `bi_extractor/parsers/base.py`.

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

class BaseParser(ABC):
    """Contract that all format-specific parsers must implement."""

    # Subclasses MUST define these as class-level attributes
    extensions: ClassVar[list[str]]   # e.g., ['.twb', '.twbx']
    tool: ClassVar[str]               # e.g., 'Tableau'

    def __init_subclass__(cls, **kwargs):
        """Validate that subclasses define required class attributes."""
        super().__init_subclass__(**kwargs)
        if not getattr(cls, 'extensions', None):
            raise TypeError(f"{cls.__name__} must define 'extensions' class attribute")
        if not getattr(cls, 'tool', None):
            raise TypeError(f"{cls.__name__} must define 'tool' class attribute")

    @abstractmethod
    def parse(self, file_path: Path) -> ExtractionResult:
        """Parse a single file and return normalized metadata."""

    def can_parse(self, file_path: Path) -> bool:
        """Check if this parser can handle the given file. Default: check extension."""
        return file_path.suffix.lower() in self.extensions

    def check_dependencies(self) -> tuple[bool, str]:
        """Check if required dependencies are available. Return (available, message)."""
        return True, "No special dependencies required"
```

**Acceptance criteria:**
- BaseParser is abstract and cannot be instantiated directly
- Subclasses that do not define `extensions` or `tool` class attributes raise TypeError at class definition time
- `parse()` accepts `pathlib.Path`, not `str`
- `check_dependencies()` provides a clear message when optional packages are missing

---

### Task 1.4 -- Build Parser Registry

Create `bi_extractor/core/registry.py` with auto-discovery using guarded imports.

```python
class ParserRegistry:
    """Discovers and manages parser instances. Maps file extensions to parsers."""

    def register(self, parser: BaseParser) -> None: ...
    def get_parser(self, file_path: Path) -> BaseParser | None: ...
    def list_parsers(self) -> list[dict]: ...           # For CLI --list-formats
    def auto_discover(self) -> None: ...                # Scan parsers/ package
    def supported_extensions(self) -> set[str]: ...
```

**Auto-discovery with guarded imports (CRITICAL):**

The registry scans `parsers/` subpackages for BaseParser subclasses. Every parser module that depends on optional packages MUST guard those imports. The registry catches `ImportError` per-module so one missing dependency never crashes the entire scan.

**Required guarded import pattern for all parsers with optional deps:**

```python
# Example: hyper_parser.py
import logging

logger = logging.getLogger(__name__)

try:
    import tableauhyperapi
    _HAS_HYPER = True
except ImportError:
    _HAS_HYPER = False

class HyperParser(BaseParser):
    extensions: ClassVar[list[str]] = ['.hyper']
    tool: ClassVar[str] = 'Tableau'

    def check_dependencies(self) -> tuple[bool, str]:
        if _HAS_HYPER:
            return True, "tableauhyperapi available"
        return False, "Install tableauhyperapi: pip install tableauhyperapi"

    def parse(self, file_path: Path) -> ExtractionResult:
        if not _HAS_HYPER:
            return ExtractionResult(
                source_file=str(file_path), file_type='hyper', tool_name='Tableau',
                errors=["tableauhyperapi not installed. Install: pip install tableauhyperapi"]
            )
        # actual parsing...
```

This pattern is a HARD RULE documented in CONTRIBUTING.md. Auto-discovery wraps each module import in try/except and logs warnings for modules that fail to import.

**Acceptance criteria:**
- Adding a new parser file with a BaseParser subclass makes it automatically available without editing registry code
- `get_parser(Path('report.twb'))` returns the Tableau parser
- `list_parsers()` returns name, extensions, dependency status for each registered parser
- Duplicate extension registration raises a clear error
- Missing optional dependencies produce log warnings, never crash the registry scan

---

### Task 1.5 -- Refactor Existing Tableau Parser

Move the existing Tableau extraction logic into `bi_extractor/parsers/tableau/twb_parser.py` as a `TableauTwbParser(BaseParser)` class.

**Key changes:**
- `extract_twb_tree()` becomes an internal method
- `extract_all_data()` becomes the core of `parse()`
- `clean_calculation_formula()` becomes a private utility method
- Output is converted from the current dict format to `ExtractionResult`
- The current 14-column CSV output must be reproducible from the new model

**Acceptance criteria:**
- Running the refactored parser against any `.twb`/`.twbx` file produces identical CSV output to the current `tableau_metadata_extractor.py`
- A regression test compares old vs new output on at least one fixture file
- No Tableau-specific logic leaks into core modules

---

### Task 1.6 -- Tableau Data Source Parser (.tds / .tdsx)

Create `bi_extractor/parsers/tableau/tds_parser.py`.

- `.tds` files are XML with the same structure as `.twb` but containing only the datasource section (no worksheets)
- `.tdsx` files are ZIP archives containing a `.tds` file (same pattern as `.twbx`)
- Reuse XML parsing utilities from the TWB parser
- Will not have worksheet usage data (only datasources, fields, calculations, connections)

**Dependencies:** None (stdlib xml.etree.ElementTree + zipfile)
**Difficulty:** LOW -- very similar to existing TWB parser

**Acceptance criteria:**
- Parses `.tds` files and extracts datasources, fields, calculations, connections
- Parses `.tdsx` files by extracting the inner `.tds`
- Returns ExtractionResult with empty `report_elements` list (no worksheets in data source files)

---

### Task 1.7 -- SSRS Parser (.rdl / .rdlc)

Create `bi_extractor/parsers/microsoft/ssrs_parser.py`.

- RDL files are XML with Microsoft's Report Definition Language schema
- Namespace: `http://schemas.microsoft.com/sqlserver/reporting/2016/01/reportdefinition` (varies by version)
- Key XML paths:
  - `//DataSources/DataSource` -- connection info
  - `//DataSets/DataSet` -- queries, fields
  - `//DataSets/DataSet/Fields/Field` -- field definitions with DataField and typenames
  - `//Body/ReportItems` -- report visual elements (Tablix, Chart, etc.)
  - `//ReportParameters/ReportParameter` -- parameters
- `.rdlc` is the same XML format (client-side variant)

**Dependencies:** None (stdlib ElementTree with namespace handling)
**Difficulty:** MEDIUM -- well-documented XML format but requires namespace awareness

**Acceptance criteria:**
- Extracts data sources with connection strings (sanitized)
- Extracts all dataset fields with names, types, and source expressions
- Extracts report parameters with defaults and allowed values
- Extracts report structure (Tablix, Chart, etc.) as ReportElements
- Handles multiple RDL schema versions (2008, 2010, 2016)

---

### Task 1.8 -- JasperReports Parser (.jrxml)

Create `bi_extractor/parsers/jasper/jrxml_parser.py`.

- JRXML files are XML with the JasperReports schema
- Key XML paths:
  - `//queryString` -- SQL queries
  - `//field` -- data fields with class types
  - `//variable` -- calculated/aggregate variables
  - `//parameter` -- report parameters
  - `//band` -- report sections (title, pageHeader, detail, summary, etc.)
  - `//textField/textFieldExpression` -- field usage in layout
  - `//dataSource` or JNDI references for connections

**Dependencies:** None (stdlib ElementTree)
**Difficulty:** MEDIUM -- well-structured XML

**Acceptance criteria:**
- Extracts fields with Java class types mapped to normalized types
- Extracts variables (JasperReports calculated fields) with expressions
- Extracts parameters with types and defaults
- Extracts report bands as ReportElements
- Maps textFieldExpression references back to field usage

---

### Task 1.9 -- BIRT Parser (.rptdesign)

Create `bi_extractor/parsers/eclipse/birt_parser.py`.

- `.rptdesign` files are XML following Eclipse BIRT's schema
- Key XML paths:
  - `//data-sources/oda-data-source` -- connection definitions
  - `//data-sets/oda-data-set` -- queries and result set columns
  - `//data-sets/oda-data-set/structure/list-property[@name='resultSetColumns']` -- field definitions
  - `//body` -- report layout elements
  - `//parameters/scalar-parameter` -- report parameters

**Dependencies:** None (stdlib ElementTree)
**Difficulty:** MEDIUM -- XML but with BIRT-specific property encoding

**Acceptance criteria:**
- Extracts ODA data source connection info
- Extracts result set columns with types from data sets
- Extracts scalar parameters
- Extracts report body structure as ReportElements

---

### Task 1.10 -- Oracle BI Publisher Parser (.xdo / .xdoz)

Create `bi_extractor/parsers/oracle/xdo_parser.py`.

- `.xdo` files are XML data templates
- `.xdoz` files are ZIP archives containing `.xdo` (handle like `.twbx`)
- Key XML paths:
  - Data model definitions with SQL queries
  - Parameter definitions
  - Data field bindings

**Dependencies:** None (stdlib ElementTree + zipfile)
**Difficulty:** MEDIUM

**Acceptance criteria:**
- Extracts data model queries and field bindings from `.xdo`
- Handles `.xdoz` by extracting inner `.xdo` from ZIP
- Extracts parameters if present

---

### Task 1.11 -- CLI Interface

Create `bi_extractor/cli/main.py` using `argparse`.

**Commands and options:**

```
bi-extractor extract <input_path> [options]
    --output, -o          Output directory (default: current directory)
    --format, -f          Output format: csv, json, excel (default: csv)
    --recursive, -r       Scan input directory recursively
    --types, -t           Filter by file types: e.g., --types twb,pbix,rdl
    --verbose, -v         Verbose output with per-file details
    --quiet, -q           Suppress all output except errors

bi-extractor list-formats
    Shows all supported formats with dependency status

bi-extractor info <file_path>
    Quick summary of a single file without full extraction

bi-extractor gui
    Launch the GUI (legacy mode)
```

**Acceptance criteria:**
- `bi-extractor extract ./reports/ -o ./output/ -f csv` processes all supported files
- `bi-extractor list-formats` shows parser name, extensions, dependency status
- `bi-extractor gui` launches the tkinter GUI
- Exit codes: 0 = success, 1 = partial failure (some files failed), 2 = total failure
- `--help` produces clear usage documentation

---

### Task 1.12 -- MOVED to Task 1.1b

Test infrastructure has been moved to Task 1.1b (immediately after package structure) per consensus review. The Tableau refactor (Task 1.5) is the highest-risk task and must have regression tests from day one.

**Test strategy (applies throughout all phases):**
- XML-based formats: minimal hand-crafted XML fixtures (50-200 lines), committed to repo
- ZIP-based formats: minimal ZIP archives in fixtures/ or built programmatically in conftest.py
- Binary/proprietary formats: mock-based testing; document how to run integration tests with real files locally
- Each parser task includes writing its own tests (not deferred to a separate task)

**Test categories:**
1. **Unit tests** -- individual parser methods, model serialization, registry lookup
2. **Integration tests** -- parse fixture files end-to-end, verify ExtractionResult contents
3. **Regression tests** -- compare Tableau parser output against golden CSV
4. **Smoke tests** -- corrupt/empty file handling per parser

**Coverage targets:** 80%+ core modules, 70%+ parsers

---

## Phase 2: ZIP-Based Parsers + Output Formatters

### Task 2.1 -- Power BI Parser (.pbix / .pbit)

Create `bi_extractor/parsers/microsoft/pbix_parser.py`.

- `.pbix` and `.pbit` are ZIP archives
- Key internal files:
  - `DataModelSchema` -- JSON containing tables, columns, relationships, measures (DAX), calculated columns
  - `Report/Layout` -- JSON containing report pages, visuals, filters
  - `[Content_Types].xml` -- manifest
- `.pbit` is a template (same structure but no data)
- The DataModelSchema may be UTF-16-LE encoded with BOM

**Dependencies:** None for basic extraction (stdlib zipfile + json). For encrypted .pbix files, would need additional handling (out of scope for initial implementation).
**Difficulty:** MEDIUM-HIGH -- well-documented but complex nested JSON structures

**Acceptance criteria:**
- Extracts tables and columns from DataModelSchema
- Extracts DAX measures and calculated columns with formulas
- Extracts relationships/joins between tables
- Extracts report pages and visual types from Report/Layout
- Extracts filters and parameters
- Handles both `.pbix` and `.pbit`
- Gracefully handles encrypted `.pbix` files with clear error message

---

### Task 2.2 -- Pentaho Parser (.prpt)

Create `bi_extractor/parsers/pentaho/prpt_parser.py`.

- `.prpt` files are ZIP archives containing XML files
- Key internal files:
  - `datadefinition.xml` -- data source queries
  - `layout.xml` -- report layout and field bindings
  - `datasources/` directory -- connection definitions
  - `meta.xml` -- report metadata

**Dependencies:** None (stdlib zipfile + ElementTree)
**Difficulty:** MEDIUM

**Acceptance criteria:**
- Extracts data source connections from datasources/ XML
- Extracts query definitions and field references
- Extracts layout structure as ReportElements
- Extracts report metadata (title, author, etc.)

---

### Task 2.3 -- Tableau Packaged Data Source (.tdsx)

Handled by the TDS parser from Task 1.6 (ZIP extraction + delegation to TDS parser). This is included here for tracking but the work is done in Phase 1.

---

### Task 2.4 -- Oracle BI Publisher Packaged (.xdoz)

Handled by the XDO parser from Task 1.10 (ZIP extraction + delegation to XDO parser). This is included here for tracking but the work is done in Phase 1.

---

### Task 2.5 -- Output Formatters (JSON + Excel)

Create additional output formatters.

**JSON Formatter** (`bi_extractor/output/json_formatter.py`):
- Output ExtractionResult as structured JSON
- Option for flat (one-object-per-field, like CSV) or hierarchical (nested by datasource/report element)
- Pretty-printed by default, compact option for piping

**Excel Formatter** (`bi_extractor/output/excel_formatter.py`):
- Multi-sheet workbook: Fields, DataSources, ReportElements, Parameters, Relationships
- Each sheet has column headers matching the model fields
- Auto-column-width and header formatting

**Dependencies:**
- JSON: None (stdlib json)
- Excel: `openpyxl` (add as optional dependency: `pip install bi-extractor[excel]`)

**Acceptance criteria:**
- JSON output round-trips: parse JSON back into ExtractionResult without data loss
- Excel output opens cleanly in Excel/LibreOffice with proper column headers
- Both formatters are registered in a formatter registry (same pattern as parsers)
- CSV formatter produces identical output to current tool

---

## Phase 3: Binary and Proprietary Parsers

These parsers require special handling due to proprietary file formats. Each has significant constraints around what metadata can realistically be extracted.

### Task 3.1 -- Crystal Reports Parser (.rpt / .rptr)

Create `bi_extractor/parsers/sap/crystal_parser.py`.

- `.rpt` files are proprietary binary format
- **Primary approach:** Use `pyCrystalReports` or COM automation via `win32com.client` (Windows only)
- **Fallback approach:** Limited binary header parsing for basic metadata
- `.rptr` is a read-only variant (same binary format)
- This parser is **Windows-only** due to COM dependency

**Dependencies:** `pywin32` (optional, Windows only)
**Difficulty:** HIGH -- requires COM automation, Windows-only
**Realistic extraction:** Database connections, tables, fields, formulas, report sections, parameters, groups

**Acceptance criteria:**
- On Windows with Crystal Reports installed: full metadata extraction via COM
- On Windows without Crystal Reports: clear error message about requirements
- On non-Windows: parser reports "unsupported platform" via check_dependencies()
- Never crashes -- always returns ExtractionResult (possibly with errors list populated)

---

### Task 3.2 -- Qlik Parsers (.qvw / .qvf / .qvd)

**QVW Parser** (`bi_extractor/parsers/qlik/qvw_parser.py`):
- `.qvw` is proprietary binary (QlikView)
- Limited extraction possible: some metadata in XML-like header blocks
- Can extract script section (load scripts contain table/field definitions)
- **Approach:** Binary scanning for known patterns + script parsing

**QVD Parser** (`bi_extractor/parsers/qlik/qvd_parser.py`):
- `.qvd` files have an XML header followed by binary data
- The XML header contains: table name, field names, field types, row count
- **Approach:** Read XML header up to the binary data marker `<EndOfHeader/>`

**QVF Parser** (`bi_extractor/parsers/qlik/qvf_parser.py`):
- `.qvf` is Qlik Sense's format (SQLite-based internally in some versions)
- Can attempt SQLite-based extraction for local files
- For cloud-hosted: needs Qlik Sense API (Phase 4)

**Dependencies:** None for QVD (XML header). `sqlite3` (stdlib) for QVF. QVW is best-effort binary parsing.
**Difficulty:** HIGH (QVW), MEDIUM (QVD), MEDIUM-HIGH (QVF)

**Acceptance criteria:**
- QVD parser extracts field names, types, and table name from XML header
- QVW parser extracts load script text and parses field/table references (best effort)
- QVF parser attempts SQLite extraction and falls back to error message
- All three handle corrupt files gracefully

---

### Task 3.3 -- SAP BusinessObjects Parsers (.wid / .unv / .unx)

Create `bi_extractor/parsers/sap/bobj_parser.py`.

- `.wid` (Web Intelligence) is proprietary binary -- very limited extraction without SAP SDK
- `.unv` (Universe Design Tool) is proprietary binary
- `.unx` (Information Design Tool) has some XML structure
- **Realistic approach:** `.unx` can be partially parsed as XML; `.wid` and `.unv` require SAP BI SDK or REST API
- Mark as "limited support" parsers

**Dependencies:** For `.unx`: None (XML-ish). For `.wid`/`.unv`: SAP RESTful Web Services SDK (optional, proprietary)
**Difficulty:** VERY HIGH -- proprietary formats with limited public documentation

**Acceptance criteria:**
- `.unx` parser extracts universe dimensions, measures, and connection info
- `.wid` and `.unv` parsers return a clear "limited support" message with whatever header metadata can be extracted
- All parsers degrade gracefully

---

### Task 3.4 -- Tableau Hyper and TDE Parsers

**Hyper Parser** (`bi_extractor/parsers/tableau/hyper_parser.py`):
- `.hyper` files are SQLite-based extracts
- Can use `tableauhyperapi` (Tableau's official Python library) or direct SQLite access
- Extracts: table names, column names, column types, row counts
- Does NOT contain formulas, worksheets, or report structure (it is a data file, not a report)

**TDE Parser** (`bi_extractor/parsers/tableau/tde_parser.py`):
- `.tde` is Tableau's legacy extract format (pre-Hyper)
- Requires `dataextract` library (deprecated) or the Tableau SDK
- Very limited tooling available
- Mark as "legacy/limited support"

**Dependencies:** `tableauhyperapi` (optional) for Hyper; `pantab` as lighter alternative. TDE has no reliable modern library.
**Difficulty:** MEDIUM (Hyper with tableauhyperapi), HIGH (TDE)

**Acceptance criteria:**
- Hyper parser extracts table schemas (tables, columns, types) when tableauhyperapi is available
- Hyper parser attempts direct SQLite fallback when tableauhyperapi is not available
- TDE parser provides "legacy format -- limited support" message with best-effort extraction
- Both return ExtractionResult with datasources and fields only (no report elements)

---

### Task 3.5 -- Oracle Reports Parser (.rdf)

Create `bi_extractor/parsers/oracle/rdf_parser.py`.

- `.rdf` is Oracle Reports' legacy binary format
- Extremely limited extraction without Oracle Reports Builder
- **Approach:** Best-effort binary header parsing; recommend users convert to XML format (.rdfx) first
- Mark as "legacy/limited support"

**Dependencies:** None
**Difficulty:** VERY HIGH -- undocumented binary format

**Acceptance criteria:**
- Attempts basic binary header parsing for metadata
- Returns clear "limited support -- consider converting to XML" message
- Never crashes on binary input

---

### Task 3.6 -- JasperReports Compiled (.jasper)

Create `bi_extractor/parsers/jasper/jasper_parser.py`.

- `.jasper` files are serialized Java objects (Java Object Serialization format)
- Cannot be parsed natively in Python without significant effort
- **Approach:** Recommend users use the source `.jrxml` instead; provide utility message
- Could potentially use `javaobj-py3` library for partial deserialization

**Dependencies:** `javaobj-py3` (optional)
**Difficulty:** HIGH

**Acceptance criteria:**
- With `javaobj-py3`: attempts to deserialize and extract field/parameter names
- Without the library: returns "use .jrxml source file instead" guidance
- Never crashes

---

## Phase 4: API-Based Extractors + Polish

### Task 4.1 -- MicroStrategy Extractor

Create `bi_extractor/parsers/microstrategy/mstr_parser.py`.

- `.mstr` files are proprietary and not parseable without MicroStrategy SDK
- **Approach:** Use MicroStrategy REST API to extract report/dashboard metadata
- Requires: MicroStrategy Library server URL + authentication credentials
- Extracts: report definitions, attributes, metrics, filters, prompts

**Dependencies:** `requests` (for REST API calls), `mstrio-py` (optional MicroStrategy SDK)
**Difficulty:** HIGH -- requires running MicroStrategy environment

**Acceptance criteria:**
- API-based extractor connects to MicroStrategy Library and extracts report metadata
- Credentials handled via environment variables or config file (never hardcoded)
- File-based `.mstr` parser returns "API extraction required" message with instructions
- Works with MicroStrategy 2021+ REST API

---

### Task 4.2 -- Qlik Sense Cloud Extractor

Extend `bi_extractor/parsers/qlik/qvf_parser.py` with API support.

- For cloud-hosted Qlik Sense apps, use the Qlik Sense REST API
- Extracts: app objects, sheets, dimensions, measures, load script, connections

**Dependencies:** `requests`, Qlik Sense API key
**Difficulty:** MEDIUM-HIGH

**Acceptance criteria:**
- API mode extracts app metadata from Qlik Sense cloud
- Falls back to local file parsing for `.qvf` files on disk
- Credentials handled via environment variables

---

### Task 4.3 -- GUI Overhaul

Modernize `bi_extractor/gui/app.py`.

**Enhancements:**
- Show supported formats and their dependency status
- File type filter in the browse dialog
- Progress bar (not just log text)
- Output format selector (CSV / JSON / Excel)
- Summary panel showing extraction results before saving
- Drag-and-drop file support (if tkinter supports it on the platform)

**Acceptance criteria:**
- GUI shows all supported formats with green/red indicators for dependency availability
- Output format is selectable
- Progress bar reflects actual progress (file X of Y)
- Results summary before writing output

---

### Task 4.4 -- Documentation and Packaging

- Update README.md with universal extractor documentation
- Add CONTRIBUTING.md with guide for writing new parsers
- Add per-parser documentation in docstrings
- Set up pyproject.toml with optional dependency groups:
  - `pip install bi-extractor` -- core + XML parsers (stdlib only)
  - `pip install bi-extractor[excel]` -- adds openpyxl
  - `pip install bi-extractor[tableau-hyper]` -- adds tableauhyperapi
  - `pip install bi-extractor[crystal]` -- adds pywin32
  - `pip install bi-extractor[qlik]` -- adds javaobj-py3
  - `pip install bi-extractor[api]` -- adds requests, mstrio-py
  - `pip install bi-extractor[all]` -- everything

**Acceptance criteria:**
- README covers installation, usage (CLI + GUI), supported formats table with extraction capabilities
- CONTRIBUTING.md walks through creating a new parser step-by-step
- `pip install bi-extractor` works from PyPI (or at least from git)
- All optional dependencies are properly declared in pyproject.toml

---

## Dependencies Summary

| Package | Purpose | Required By | Phase |
|---|---|---|---|
| (stdlib) | XML, ZIP, CSV, JSON, argparse, tkinter | Core, all XML/ZIP parsers | 1 |
| `openpyxl` | Excel output | Excel formatter | 2 |
| `tableauhyperapi` | Tableau Hyper extracts | Hyper parser | 3 |
| `pywin32` | COM automation (Windows) | Crystal Reports parser | 3 |
| `javaobj-py3` | Java serialization | .jasper parser | 3 |
| `requests` | REST API calls | MicroStrategy, Qlik Cloud | 4 |
| `mstrio-py` | MicroStrategy SDK | MicroStrategy extractor | 4 |
| `pytest` | Testing | Development (`[dev]` extra) | 1 |
| `pytest-cov` | Coverage reporting | Development (`[dev]` extra) | 1 |
| `mypy` | Type checking | Development (`[dev]` extra) | 1 |

**Design principle:** The core package and all XML/ZIP parsers run on stdlib only. Every third-party dependency is optional and isolated to specific parsers. Missing dependencies result in clear messages, never import errors.

---

## Parser Difficulty and Priority Matrix

| Format | Extensions | Parse Method | Difficulty | Phase | Realistic Extraction |
|---|---|---|---|---|---|
| Tableau Workbook | .twb, .twbx | XML + ZIP | LOW | 1 | FULL (already done) |
| Tableau Data Source | .tds, .tdsx | XML + ZIP | LOW | 1 | FULL (connections, fields, calcs) |
| SSRS | .rdl, .rdlc | XML | MEDIUM | 1 | FULL (datasets, fields, params, layout) |
| JasperReports | .jrxml | XML | MEDIUM | 1 | FULL (fields, variables, params, layout) |
| BIRT | .rptdesign | XML | MEDIUM | 1 | FULL (data sets, fields, params, layout) |
| Oracle BI Publisher | .xdo, .xdoz | XML + ZIP | MEDIUM | 1 | HIGH (data model, fields, params) |
| Power BI | .pbix, .pbit | ZIP + JSON | MEDIUM-HIGH | 2 | HIGH (tables, DAX, relationships, visuals) |
| Pentaho | .prpt | ZIP + XML | MEDIUM | 2 | HIGH (connections, queries, layout) |
| Qlik Data File | .qvd | XML header | MEDIUM | 3 | PARTIAL (field names, types, table name) |
| Tableau Hyper | .hyper | SQLite | MEDIUM | 3 | PARTIAL (tables, columns, types -- data file only) |
| Qlik Sense | .qvf | SQLite / API | MEDIUM-HIGH | 3/4 | PARTIAL to FULL (depends on local vs cloud) |
| QlikView | .qvw | Binary scan | HIGH | 3 | LIMITED (load script, some metadata) |
| Crystal Reports | .rpt, .rptr | COM (Win) | HIGH | 3 | FULL on Windows, NONE elsewhere |
| SAP BO Universe | .unx | XML-ish | HIGH | 3 | PARTIAL (dimensions, measures) |
| Tableau TDE | .tde | Binary | HIGH | 3 | LIMITED (legacy, minimal tooling) |
| JasperReports compiled | .jasper | Java serial | HIGH | 3 | LIMITED (field names if deserialization works) |
| SAP BO Web Intelligence | .wid | Binary | VERY HIGH | 3 | VERY LIMITED (header metadata only) |
| SAP BO Universe (legacy) | .unv | Binary | VERY HIGH | 3 | VERY LIMITED |
| Oracle Reports | .rdf | Binary | VERY HIGH | 3 | VERY LIMITED (recommend XML conversion) |
| MicroStrategy | .mstr | API | HIGH | 4 | FULL via API, NONE from file |
| Qlik Sense Cloud | .qvf (cloud) | API | MEDIUM-HIGH | 4 | FULL via API |

---

## Success Criteria (Overall Project)

1. **Phase 1 complete:** Architecture refactored, 6 XML parsers working, CLI functional, test suite passing at 80%+ coverage on core modules
2. **Phase 2 complete:** Power BI and Pentaho parsers working, JSON and Excel output available
3. **Phase 3 complete:** All binary parsers implemented with appropriate "limited support" messaging for truly opaque formats
4. **Phase 4 complete:** API-based extractors for MicroStrategy and Qlik Cloud, GUI modernized, documentation complete, package published
5. **At all phases:** Existing Tableau CSV output remains backward-compatible, no parser crashes the application, `bi-extractor list-formats` accurately reflects what is available

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| **Tableau refactor regression** | Refactored parser produces different output than current code | Golden CSV fixture committed BEFORE refactoring. Data-equivalent regression test runs on every change. Task 1.1b creates this safety net. |
| **Row ordering for backward compat** | Column IDs depend on file traversal order and dict insertion order | Use `list` (not `set`/`dict`) for all collections. Document that row order matches `os.walk()` traversal + insertion order. |
| **GUI threading** | Long-running parsers (Crystal Reports COM) freeze the GUI | Engine runs in background thread via `threading.Thread`. GUI polls via `after()`. Never call `self.update()` from main thread during extraction. |
| **Cross-platform path handling** | ZIP internal paths use `/`, Windows uses `\` | Use `pathlib.PurePosixPath` for ZIP internals, `pathlib.Path` for filesystem. Document convention in CONTRIBUTING.md. |
| Binary format reverse-engineering proves impossible for some formats | Parsers for .wid, .unv, .rdf produce minimal output | Set expectations early: mark as "limited support" in docs. Recommend users export to open formats. |
| Crystal Reports COM automation is fragile | Parser only works on specific Windows + CR version combinations | Extensive error handling, version detection, clear prerequisites in docs. |
| Power BI .pbix internal format changes between versions | Parser breaks on newer .pbix files | Version detection from [Content_Types].xml, test against multiple PBI Desktop versions. |
| Metadata model is too rigid for all BI tools | Some tool-specific metadata is lost | The `metadata: dict[str, Any]` catch-all field in ExtractionResult captures tool-specific extras. Each parser documents its keys. |
| Scope creep from 22 formats | Project never reaches completion | Strict phasing. Each phase is independently valuable. Ship Phase 1 as MVP. |
| **Auto-discovery import crash** | One parser with bare optional import crashes entire app | Guarded import pattern is a HARD RULE. Registry catches ImportError per-module. Enforced in code review and CONTRIBUTING.md. |
