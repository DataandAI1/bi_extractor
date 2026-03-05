# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for BI Metadata Extractor — single-file, no-install, no-admin .exe."""

import sys
from pathlib import Path

block_cipher = None

# All parser modules must be listed explicitly because the registry uses
# pkgutil.walk_packages() for auto-discovery, which PyInstaller cannot trace.
hidden_imports = [
    # --- parsers (auto-discovered at runtime) ---
    "bi_extractor.parsers",
    "bi_extractor.parsers.tableau",
    "bi_extractor.parsers.tableau.twb_parser",
    "bi_extractor.parsers.tableau.tds_parser",
    "bi_extractor.parsers.tableau.hyper_parser",
    "bi_extractor.parsers.microsoft",
    "bi_extractor.parsers.microsoft.pbix_parser",
    "bi_extractor.parsers.microsoft.ssrs_parser",
    "bi_extractor.parsers.qlik",
    "bi_extractor.parsers.qlik.qvd_parser",
    "bi_extractor.parsers.qlik.qvf_parser",
    "bi_extractor.parsers.cognos",
    "bi_extractor.parsers.cognos.cpf_parser",
    "bi_extractor.parsers.cognos.deployment_parser",
    "bi_extractor.parsers.jasper",
    "bi_extractor.parsers.jasper.jrxml_parser",
    "bi_extractor.parsers.eclipse",
    "bi_extractor.parsers.eclipse.birt_parser",
    "bi_extractor.parsers.oracle",
    "bi_extractor.parsers.oracle.xdo_parser",
    "bi_extractor.parsers.microstrategy",
    "bi_extractor.parsers.microstrategy.mstr_parser",
    "bi_extractor.parsers.pentaho",
    "bi_extractor.parsers.sap",
    # --- optional deps (include if installed; won't crash if absent) ---
    "tkinterdnd2",
    "javaobj",
    "cabarchive",
    "openpyxl",
]

a = Analysis(
    ["bi_extractor/gui/__main__.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude heavy optional deps that most users won't need in
        # a portable build.  Remove a line here to include it.
        "tableauhyperapi",   # ~200 MB native libs — Tableau .hyper support
        "mstrio",            # MicroStrategy REST API client
        "pywin32",           # Crystal Reports COM automation
        # Dev / test only
        "pytest",
        "mypy",
        "pytest_cov",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="bi-extractor-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,            # No console window (GUI app)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)
