# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Word to S1000D comparison application.
One-folder mode, console EXE. Run with:
    pyinstaller word_to_s1000d.spec --noconfirm
"""

import os

PROJECT_ROOT = os.path.abspath('.')

# ---------------------------------------------------------------------------
# Data files bundled into _internal (sys._MEIPASS)
# ---------------------------------------------------------------------------
datas = [
    # XSD schema files (~30 files)
    (os.path.join(PROJECT_ROOT, 'xsd'), 'xsd'),

    # Parsing rules
    (os.path.join(PROJECT_ROOT, 'parsing_rules.json'), '.'),

    # Flask templates
    (os.path.join(PROJECT_ROOT, 'comparison_app', 'templates'),
     os.path.join('comparison_app', 'templates')),

    # Flask static assets (CSS, JS, pdf.js)
    (os.path.join(PROJECT_ROOT, 'comparison_app', 'static'),
     os.path.join('comparison_app', 'static')),

    # Build number fallback for version.py in frozen mode
    (os.path.join(PROJECT_ROOT, '_build_number'), '.'),
]

# ---------------------------------------------------------------------------
# Hidden imports — lazy/deferred imports invisible to PyInstaller tracer
# ---------------------------------------------------------------------------
hiddenimports = [
    # pywin32 (COM automation for Word)
    'win32com.client',
    'win32com.server',
    'pythoncom',
    'pywintypes',
    'win32api',

    # PyMuPDF (dual fitz/pymupdf interface)
    'fitz',
    'pymupdf',
    'pymupdf.mupdf',
    'pymupdf.utils',

    # lxml C extensions
    'lxml',
    'lxml.etree',
    'lxml._elementpath',

    # python-docx
    'docx',
    'docx.oxml',
    'docx.oxml.shape',

    # mammoth
    'mammoth',

    # Pillow
    'PIL',
    'PIL.Image',

    # Flask ecosystem
    'flask',
    'jinja2',
    'jinja2.ext',
    'werkzeug',
    'markupsafe',

    # Internal project modules (lazy imports from app.py function bodies)
    'main',
    'app_paths',
    'version',
    'verify_loop',
    'raw_to_structured',
    'parsers.dmc_parser',
    'parsers.doc_converter',
    'parsers.elements_analyzer',
    'parsers.hybrid_matcher',
    'parsers.illustration_parser',
    'parsers.text_parser',
    'parsers.table_parser',
    'parsers.list_parser',
    'parsers.content_analyzer',
    'parsers.multi_sheet_illustration_parser',
    'parsers.multi_sheet_illustration_parser_fixed',
    'generators.s1000d_generator',
    'generators.pm_generator',
    'processing_scripts.descriptive_processor',
    'processing_scripts.procedure_processor',
    'comparison_app.pdf_block_extractor',
    'comparison_app.procedural_pdf_matcher',
    'comparison_app.headless_extractor',
    'comparison_app.headless_comparator',
    'comparison_app.reference_store',
    'comparison_app.pair_resolver',
    'comparison_app.docx_renderer',
    'comparison_app.s1000d_renderer',
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------
a = Analysis(
    [os.path.join('comparison_app', 'app.py')],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'test',
        'pydoc',
        'xmlrpc',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# EXE — console mode
# ---------------------------------------------------------------------------
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='word_to_s1000d',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# ---------------------------------------------------------------------------
# COLLECT — one-folder output to dist/word_to_s1000d/
# ---------------------------------------------------------------------------
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='word_to_s1000d',
)
