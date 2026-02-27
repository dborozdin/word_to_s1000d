# Project: Word to S1000D Converter

## Allowed tools

Allow all Bash commands without prompting, including curl, python, pip, git, and any other shell commands needed for development and testing.

## Permanent permissions

- XML validation commands (XSD validation, xmllint, python scripts for XML checking) are always allowed without prompting
- Running python scripts for testing, verification loops, and element analysis is always allowed
- Running inline python scripts (`python -c "..."`) for diagnostics, debugging, XML/JSON inspection, and algorithm analysis is always allowed without prompting
- Reading/writing generated XML files in tg_web/suites/ is always allowed

## Language

- All explanations, comments to the user, and descriptions of algorithm behavior must be in Russian
- Technical terms, function names, variable names, file paths, and code snippets may remain in English

## Architecture reference

**FIRST STEP after context loss:** Read `docs/algorithm_description.html` — full description of the pipeline, data flow, and current implementation status (HTML, ~900 lines). Covers:
- Part I: XML generation (Word parsing → element analysis → XML → XSD validation)
- Part II: Accuracy control (comparison app, PDF/XML markup, reference system, "Format according to reference")
- Part III: Quality criteria
- Part IV: Pipeline diagrams
- Part V: Hybrid PDF+DOCX approach (reference matching algorithm)
- Part VI: Stable element IDs (stable_id content-hash, sidecar JSON, 3-phase comparison)
- Part VII: Client module architecture (ES6 modules, see `docs/comparison_module_spec.md`)
- Part VIII: Python module specs (see `docs/python_modules_spec.md`)

**For comparison module debugging:** Read `docs/comparison_module_spec.md` — detailed spec of all 14 ES6 modules, shared state, sync pipeline, edit mode flow, data schemas.

**For Python pipeline debugging:** Read `docs/python_modules_spec.md` — detailed spec of elements_analyzer, descriptive_processor, hybrid_matcher, headless_extractor/comparator.

## Mandatory rule: keep algorithm_description.html up to date

**При любых значительных изменениях алгоритма** (новые модули, изменение pipeline,
новые типы элементов, новые маршруты API) — обновить `docs/algorithm_description.html`
в том же коммите **без дополнительного запроса** от пользователя.

## Key files map

| File | Role |
|------|------|
| `parsers/elements_analyzer.py` | Element analysis of DOCX + `apply_reference_markup()` + `compute_stable_id()` for content-hash IDs |
| `processing_scripts/descriptive_processor.py` | Generates descriptive S1000D XML + sidecar `_element_map.json` with stable_id mapping |
| `generators/s1000d_generator.py` | XML wrapper, XSD validation, XSD element ordering |
| `comparison_app/app.py` | Flask comparison app (PDF left panel ↔ XML right panel) |
| `comparison_app/s1000d_renderer.py` | Renders S1000D XML → HTML, emits `data-element-id` from sidecar |
| `comparison_app/headless_extractor.py` | Data structures (ElementInfo, ComparisonReport) + extraction from DOCX/XML |
| `comparison_app/headless_comparator.py` | 4-phase element comparison (stable_id → text → LCS → substring) + re-exports from extractor |
| `comparison_app/static/js/comparison.js` | Entry point (~60 lines): imports all modules, initializes app lifecycle |
| `comparison_app/static/js/modules/` | 14 ES6 modules (see `docs/comparison_module_spec.md` for details): |
| `  modules/state.js` | Centralized shared state + DOM refs with getters/setters |
| `  modules/badges.js` | Badge injection, rebuild lifecycle, hook registry for sync modules |
| `  modules/pdf-sync.js` | PDF marker ↔ reference sync (bbox text matching + logging) |
| `  modules/html-sync.js` | HTML element ↔ reference sync (text/sequential) |
| `  modules/xml-sync.js` | S1000D 3-phase matching (stable_id → text → type-group) |
| `  modules/edit-mode.js` | Context menu, CRUD ops, merge/split/delete/create |
| `  modules/mismatch.js` | Mismatch detection, LCS, issue navigation |
| `  modules/verification.js` | Verify loop, XSD issues, S1000D panel refresh |
| `  modules/navigation.js` | Annotation navigation, keyboard shortcuts |
| `  modules/pdf-overlay.js` | PDF page overlay creation (server blocks + JS fallback) |
| `parsers/hybrid_matcher.py` | Hybrid PDF↔XML↔DOCX matching (2-pass window + global scan) |
| `comparison_app/static/css/comparison.css` | CSS entry point (@import modules), see `static/css/modules/` |
| `comparison_app/static/css/modules/` | 11 CSS modules: base, header, layout, docx-content, s1000d-content, annotations, pdf-overlay, mismatch, context-menu, panels, modal |
| `comparison_app/reference_store.py` | CRUD for reference markup (`_references/*.json`), stores `stable_id` |
| `comparison_app/_references/` | Reference JSON files (the "ground truth" element markup) |
| `comparison_app/pdf_block_extractor.py` | Extracts text blocks from PDF via PyMuPDF for left panel |
| `verify_loop.py` | Orchestrator: reference → conversion → comparison → XSD |
| `docs/algorithm_description.html` | Full algorithm and architecture description |
| `docs/comparison_module_spec.md` | Detailed spec of 14 ES6 client modules |
| `docs/python_modules_spec.md` | Detailed spec of Python pipeline modules |
