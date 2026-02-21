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

## Key files map

| File | Role |
|------|------|
| `parsers/elements_analyzer.py` | Element analysis of DOCX + `apply_reference_markup()` + `compute_stable_id()` for content-hash IDs |
| `processing_scripts/descriptive_processor.py` | Generates descriptive S1000D XML + sidecar `_element_map.json` with stable_id mapping |
| `generators/s1000d_generator.py` | XML wrapper, XSD validation, XSD element ordering |
| `comparison_app/app.py` | Flask comparison app (PDF left panel ↔ XML right panel) |
| `comparison_app/s1000d_renderer.py` | Renders S1000D XML → HTML, emits `data-element-id` from sidecar |
| `comparison_app/headless_comparator.py` | 3-phase element comparison: stable_id → text similarity → LCS fallback |
| `comparison_app/static/js/comparison.js` | Client-side: annotations, ID-based navigation, 3-level mismatch highlighting |
| `comparison_app/reference_store.py` | CRUD for reference markup (`_references/*.json`), stores `stable_id` |
| `comparison_app/_references/` | Reference JSON files (the "ground truth" element markup) |
| `comparison_app/pdf_block_extractor.py` | Extracts text blocks from PDF via PyMuPDF for left panel |
| `verify_loop.py` | Orchestrator: reference → conversion → comparison → XSD |
| `docs/algorithm_description.html` | Full algorithm and architecture description |
