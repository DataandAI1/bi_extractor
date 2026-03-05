# Open Questions

## universal-bi-extractor - 2026-03-04

- [ ] **Project naming:** Should the package be called `bi_extractor`, `bi_metadata_extractor`, or something else? This affects the PyPI name, CLI command, and all imports.
- [ ] **Python version floor:** What is the minimum Python version to support? Python 3.10+ enables modern type syntax (`list[str]` instead of `List[str]`, match/case). Python 3.8+ would maximize compatibility but limits language features.
- [ ] **Backward compatibility strictness:** When the Tableau parser is refactored, should the CSV output be byte-for-byte identical to the current tool, or is column-for-column data equivalence sufficient (allowing row ordering or whitespace differences)?
- [ ] **Encrypted .pbix handling:** Power BI Desktop can produce encrypted .pbix files. Should the parser attempt decryption (adds significant complexity) or just report "encrypted file -- cannot extract" and move on?
- [ ] **Crystal Reports version scope:** Crystal Reports COM automation behavior varies across CR versions (2008, 2011, 2013, 2016, 2020). Which versions should be tested and supported? Or is "best effort with latest available" acceptable?
- [ ] **API credential management for Phase 4:** MicroStrategy and Qlik Cloud extractors need authentication. Should credentials be handled via environment variables only, or should a config file format (e.g., `.bi-extractor.toml`) be defined?
- [ ] **Monorepo vs single package:** Should all parsers live in one package with optional dependencies, or should heavy/proprietary parsers (Crystal, MicroStrategy) be split into separate installable packages?
- [ ] **Data sanitization policy:** Connection strings may contain server names, database names, or even embedded credentials. What level of sanitization should be applied by default? Options: (a) extract everything as-is, (b) redact passwords only, (c) redact full connection strings and keep only connection type.
- [ ] **"Limited support" parser threshold:** For formats like .wid, .unv, .rdf where extraction is minimal (maybe just file name and format type), is it worth including a parser at all, or should those be deferred until real user demand exists?
- [ ] **GUI framework:** The current GUI uses tkinter (stdlib). For the Phase 4 GUI overhaul, should it stay on tkinter (no new dependencies) or consider alternatives like `customtkinter` (modern look, still lightweight)?

## gui-implementation - 2026-03-04

- [ ] **tkinterdnd2 version pinning:** tkinterdnd2 has had breaking changes between versions. Should we pin to `>=0.4,<1.0` or leave it open? This matters because the DnD API surface differs across versions. -- Affects drag-and-drop reliability on user machines.
- [ ] **Treeview row limit / virtualization:** If a user extracts thousands of files with tens of thousands of fields, ttk.Treeview performance degrades. Should we add pagination (e.g., 500 rows per page) or lazy loading? Or is the expected data volume small enough that this is not a concern? -- Affects detail table usability at scale.
- [ ] **Formula tooltip implementation:** Full formula text in a tooltip can be very long (multi-line SQL). Should the tooltip be a simple hover popup, or a modal dialog triggered by double-click? -- Affects UX for formula-heavy reports.
- [ ] **GUI testing on CI:** tkinter tests require a display server. Should GUI widget tests be marked with `@pytest.mark.skipif` when no display is available, or should we use `xvfb` on Linux CI? Windows CI has a display available. -- Affects CI pipeline configuration.
- [ ] **Dark mode / theme support:** ttk supports themes (clam, alt, default, classic on all platforms; vista/winnative on Windows). Should the GUI use the platform default theme, or should a specific theme be chosen for consistency? Should dark mode be considered for initial release? -- Affects visual polish vs. scope.
