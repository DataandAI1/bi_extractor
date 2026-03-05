"""Shared test fixtures for bi_extractor tests."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def tableau_fixtures_dir(fixtures_dir: Path) -> Path:
    """Return the path to Tableau test fixtures."""
    return fixtures_dir / "tableau"


@pytest.fixture
def ssrs_fixtures_dir(fixtures_dir: Path) -> Path:
    """Return the path to SSRS test fixtures."""
    return fixtures_dir / "ssrs"


@pytest.fixture
def jasper_fixtures_dir(fixtures_dir: Path) -> Path:
    """Return the path to JasperReports test fixtures."""
    return fixtures_dir / "jasper"


@pytest.fixture
def birt_fixtures_dir(fixtures_dir: Path) -> Path:
    """Return the path to BIRT test fixtures."""
    return fixtures_dir / "birt"


@pytest.fixture
def oracle_fixtures_dir(fixtures_dir: Path) -> Path:
    """Return the path to Oracle BI test fixtures."""
    return fixtures_dir / "oracle"


@pytest.fixture
def cognos_fixtures_dir(fixtures_dir: Path) -> Path:
    """Return the path to IBM Cognos test fixtures."""
    return fixtures_dir / "cognos"
