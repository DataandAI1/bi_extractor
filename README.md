# BI Metadata Extractor

A universal metadata extraction tool for Business Intelligence (BI) report files. It extracts comprehensive metadata from various BI formats and exports it to a structured CSV format.

## Supported Tools and Formats

| Tool | Supported Extensions |
| :--- | :--- |
| **Tableau** | .twb, .twbx, .tds, .tdsx |
| **Microsoft SSRS** | .rdl, .rdlc |
| **JasperReports** | .jrxml |
| **BIRT** | .rptdesign |
| **Oracle BI Publisher** | .xdo, .xdoz |

## Features

- **Multi-Format Support**: Single tool for extracting metadata across different BI platforms.
- **Comprehensive Field Extraction**: Extracts fields, dimensions, measures, and calculated fields.
- **Calculation Resolution**: Automatically resolves calculation IDs to human-readable names where possible.
- **Connection Details**: Captures data source connection information.
- **Batch Processing**: Process multiple files and directories in a single run.
- **Search & Discovery**: Recursively scans directories to find and process all supported BI files.

## Output Format

The tool generates a single CSV file (`BI_Metadata.csv`) with the following columns:

- **Column ID**: Sequential identifier across all processed files
- **Column Name**: Technical field name
- **Column Alias**: User-friendly display name
- **Field Type**: Dimension, Measure, Calculated Field, etc.
- **Connection Name**: Data source connection details
- **Connection Alias**: Data source display name
- **datatype**: Data type (string, integer, etc.)
- **role**: Field role (dimension/measure)
- **Calculation Formula**: Cleaned formula with resolved references
- **Original Calculation**: Raw formula from source
- **Calc Clean Status**: Success, Partially Resolved, or No Calculation
- **Field Used in Worksheets**: Yes/No indicator
- **Worksheet Name**: Name of report element/worksheet using the field
- **File Name**: Source file name
- **Tool**: BI tool name (e.g., Tableau, SSRS)
- **File Type**: Extension of the source file
- **Parameter Count**: Number of parameters in the report
- **Relationship Count**: Number of relationships/joins identified
- **Extraction Errors**: Details of any issues encountered during extraction

## Requirements

- Python 3.8+
- Standard library (some specialized parsers may have optional dependencies)

## Usage

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

## License

This tool is provided for metadata extraction and documentation purposes.
