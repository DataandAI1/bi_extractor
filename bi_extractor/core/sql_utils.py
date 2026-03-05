"""SQL detection and extraction utilities.

Provides functions for detecting embedded SQL statements in text,
extracting table names from SQL queries, and normalizing SQL text.
Used by parsers to populate the standardized SQLQuery model.
"""

from __future__ import annotations

import re

# SQL keywords that indicate the start of a SQL statement
_SQL_KEYWORDS = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|MERGE|WITH|EXEC|EXECUTE|CALL)\b",
    re.IGNORECASE,
)

# FROM/JOIN clause table extraction
_SQL_TABLE_RE = re.compile(
    r"(?:FROM|JOIN)\s+(?:\[?(\w+)\]?\.)?(?:\[?(\w+)\]?\.)?(\[?\w+\]?)",
    re.IGNORECASE,
)

# Common SQL-like patterns that confirm SQL presence (beyond just keywords)
_SQL_PATTERNS = re.compile(
    r"\b(?:"
    r"SELECT\s+.+?\s+FROM\b"
    r"|INSERT\s+INTO\b"
    r"|UPDATE\s+\w+\s+SET\b"
    r"|DELETE\s+FROM\b"
    r"|CREATE\s+(?:TABLE|VIEW|PROCEDURE|FUNCTION)\b"
    r"|ALTER\s+(?:TABLE|VIEW)\b"
    r"|DROP\s+(?:TABLE|VIEW)\b"
    r"|MERGE\s+INTO\b"
    r"|WITH\s+\w+\s+AS\s*\("
    r"|EXEC(?:UTE)?\s+\w+"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def contains_sql(text: str) -> bool:
    """Check if a text string contains SQL statements.

    Uses pattern matching to detect common SQL statement structures.
    Returns True if the text appears to contain SQL, False otherwise.

    Args:
        text: The text to check for SQL content.

    Returns:
        True if SQL patterns are detected, False otherwise.
    """
    if not text or not text.strip():
        return False
    return bool(_SQL_PATTERNS.search(text))


def extract_tables_from_sql(sql: str) -> list[str]:
    """Extract table names from SQL FROM/JOIN clauses.

    Parses SQL text for FROM and JOIN clauses and extracts table names,
    handling optional schema and database prefixes.

    Args:
        sql: The SQL query text to parse.

    Returns:
        Deduplicated list of table names found in the query.
    """
    tables: list[str] = []
    seen: set[str] = set()
    for match in _SQL_TABLE_RE.finditer(sql):
        # group(3) is always the table name; group(2) may be schema
        table_name = match.group(3).strip("[]")
        if table_name.lower() not in seen:
            seen.add(table_name.lower())
            tables.append(table_name)
    return tables


def normalize_sql(sql: str) -> str:
    """Normalize SQL text by collapsing whitespace and trimming.

    Args:
        sql: Raw SQL text that may contain excessive whitespace.

    Returns:
        Cleaned SQL text with normalized whitespace.
    """
    if not sql:
        return ""
    # Collapse runs of whitespace (including newlines) into single spaces
    return " ".join(sql.split()).strip()
