# BI Metadata Extractor

A universal metadata extraction tool for Business Intelligence (BI) report files. It extracts comprehensive metadata from various BI formats and exports it to structured CSV files. Available as both a command-line tool and a standalone GUI application.

## Supported Tools and Formats

| Tool | Supported Extensions | Optional Dependencies |
| :--- | :--- | :--- |
| **Tableau** | .twb, .twbx, .tds, .tdsx | — |
| **Tableau Hyper** | .hyper | `tableauhyperapi` |
| **Microsoft SSRS / Power BI Paginated** | .rdl, .rdlc | — |
| **Microsoft Power BI Desktop** | .pbix | — |
| **IBM Cognos Analytics** | .cpf (Framework Manager projects) | — |
| **IBM Cognos Deployment** | .cab (deployment archives) | `cabarchive` |
| **JasperReports** | .jrxml | — |
| **Eclipse BIRT** | .rptdesign | — |
| **Oracle BI Publisher** | .xdo, .xdoz | — |
| **QlikView** | .qvd | — |
| **Qlik Sense** | .qvf | — |
| **MicroStrategy** | .mstr | — |

## Features

- **Multi-Format Support**: Single tool for extracting metadata across 12 BI platforms.
- **Comprehensive Field Extraction**: Extracts fields, dimensions, measures, and calculated fields.
- **Embedded SQL Extraction**: Detects and extracts SQL queries embedded in report definitions (RDL, Cognos, BIRT, Jasper, XDO, PBIX).
- **Calculation Resolution**: Automatically resolves calculation IDs to human-readable names where possible.
- **Connection Details**: Captures data source connection information.
- **Relationships & Joins**: Identifies table relationships and join definitions.
- **Parameters & Filters**: Extracts report parameters and filter definitions.
- **Batch Processing**: Process multiple files and directories in a single run.
- **Search & Discovery**: Recursively scans directories to find and process all supported BI files.
- **GUI Application**: Standalone desktop application with drag-and-drop support, available as a single .exe (no install required).

## Output Format

### Main Metadata CSV (`BI_Metadata.csv`)

One row per field-per-worksheet combination with the following columns:

| Column | Description |
| :--- | :--- |
| Column ID | Sequential identifier across all processed files |
| Column Name | Technical field name |
| Column Alias | User-friendly display name |
| Field Type | regular, calculated, etc. |
| Connection Name | Data source connection details |
| Connection Alias | Data source display name |
| datatype | Data type (string, integer, float, etc.) |
| role | Field role (dimension/measure) |
| Calculation Formula | Cleaned formula with resolved references |
| Original Calculation | Raw formula from source |
| Calc Clean Status | Success, Partially Resolved, or No Calculation |
| Field Used in Worksheets | Yes/No indicator |
| Worksheet Name | Name of report element/worksheet using the field |
| File Name | Source file name |
| Tool | BI tool name (e.g., Tableau, SSRS) |
| File Type | Extension of the source file |
| Parameter Count | Number of parameters in the report |
| Relationship Count | Number of relationships/joins identified |
| SQL Query Count | Number of embedded SQL queries found |
| SQL Queries | Truncated summary of embedded SQL |
| Extraction Errors | Details of any issues encountered during extraction |

### SQL Queries CSV (`BI_SQL_Queries.csv`)

When embedded SQL is found, a separate file is produced with full, untruncated SQL text:

| Column | Description |
| :--- | :--- |
| Source File | Report file the SQL came from |
| Tool | BI tool name |
| Query Name | SQL query identifier |
| Dataset | Dataset or query subject name |
| Datasource | Connection/datasource name |
| Tables Referenced | Tables extracted from FROM/JOIN clauses |
| SQL Text | Full SQL query text (not truncated) |

## Requirements

- Python 3.10+
- Standard library only for most parsers (some specialized parsers have optional dependencies — see table above)

## Usage

### GUI Application

Run the standalone executable (no Python required):

```
bi-extractor-gui.exe
```

Or launch from Python:

```bash
python -m bi_extractor.gui
```

### Command Line Interface

```bash
# Extract metadata from all supported files in a directory
python -m bi_extractor.cli.main extract /path/to/bi/files -o /output/dir

# List all supported formats and their status
python -m bi_extractor.cli.main list-formats

# Show metadata summary for a single file
python -m bi_extractor.cli.main info /path/to/file.twb
```

### Options

- `-o, --output DIR`: Specify output directory (default: current directory)
- `-r, --recursive`: Scan subdirectories (default: true)
- `-t, --types twb,rdl`: Only process specific extensions
- `-v, --verbose`: Enable verbose logging

## Building the Standalone Executable

```bash
pip install pyinstaller
python -m PyInstaller bi-extractor-gui.spec --noconfirm
```

The output is a single file at `dist/bi-extractor-gui.exe`.

## License

This tool is provided for metadata extraction and documentation purposes.
