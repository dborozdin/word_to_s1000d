"""
CRUD operations for reference markup JSON files.
Each DMC gets a JSON file in _references/ storing the user-edited
'ground truth' element list for that document.
"""

import os
import json
import hashlib
from datetime import datetime
from typing import Optional

REFERENCE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_references')


def _ensure_dir():
    os.makedirs(REFERENCE_DIR, exist_ok=True)


def _ref_path(dmc_string: str) -> str:
    return os.path.join(REFERENCE_DIR, f'{dmc_string}.json')


def _file_hash(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return f'sha256:{h.hexdigest()[:16]}'


def get_reference(dmc_string: str) -> Optional[dict]:
    """
    Load reference markup for a DMC.
    Returns dict with keys: dmc_string, docx_hash, created_at, modified_at, source, elements.
    Returns None if no reference exists.
    """
    path = _ref_path(dmc_string)
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_reference(dmc_string: str, elements: list, source: str = 'manual') -> dict:
    """
    Save reference markup for a DMC.

    Args:
        dmc_string: DMC identifier
        elements: List of element dicts [{idx, type, text_start, text_end}, ...]
        source: 'auto', 'manual', or 'auto+manual'

    Returns:
        The saved reference dict.
    """
    _ensure_dir()
    path = _ref_path(dmc_string)

    existing = get_reference(dmc_string)
    now = datetime.now().isoformat(timespec='seconds')

    ref = {
        'dmc_string': dmc_string,
        'docx_hash': existing.get('docx_hash', '') if existing else '',
        'created_at': existing.get('created_at', now) if existing else now,
        'modified_at': now,
        'source': source,
        'elements': elements,
    }

    with open(path, 'w', encoding='utf-8') as f:
        json.dump(ref, f, ensure_ascii=False, indent=2)

    return ref


def _init_reference_hybrid(dmc_string: str, docx_path: str) -> list:
    """Build reference elements via hybrid PDF+DOCX pipeline (with element_id)."""
    import configparser as _cp

    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _cfg = _cp.ConfigParser()
    _cfg.read(os.path.join(_project_root, 'config.ini'), encoding='utf-8')
    output_dir = os.path.join(_project_root, _cfg.get('processing', 'output_dir', fallback='./tg_web/suites/66935'))

    from comparison_app.docx_renderer import render_docx_to_pdf, is_word_available
    if not is_word_available():
        raise RuntimeError('Hybrid mode requires MS Word for PDF rendering')

    pdf_path = render_docx_to_pdf(docx_path, dmc_string)

    from comparison_app.pdf_block_extractor import extract_pdf_blocks_full
    from docx import Document
    from parsers.elements_analyzer import analyze_document_elements
    from parsers.hybrid_matcher import match_pdf_to_docx

    pdf_pages = extract_pdf_blocks_full(pdf_path)
    doc = Document(docx_path)
    docx_elements = analyze_document_elements(doc)
    unified = match_pdf_to_docx(pdf_pages, docx_elements)

    element_dicts = []
    for ue in unified:
        d = {
            'idx': ue.idx,
            'type': ue.type,
            'type_source': ue.type_source,
            'text_start': ue.text_start,
            'text_end': ue.text_end,
            'span': ue.span,
            'element_id': ue.element_id,
        }
        element_dicts.append(d)

    return element_dicts


def init_reference_from_auto(dmc_string: str, docx_path: str) -> dict:
    """
    Create initial reference from automatic docx element extraction.

    In hybrid mode (element_source=hybrid in config.ini), uses PDF+DOCX
    matching pipeline which provides element_id for stable identification.
    Otherwise falls back to mammoth-based HTML parsing.

    Args:
        dmc_string: DMC identifier
        docx_path: Path to the source .docx file

    Returns:
        The created reference dict.
    """
    import configparser as _cp

    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _cfg = _cp.ConfigParser()
    _cfg.read(os.path.join(_project_root, 'config.ini'), encoding='utf-8')
    element_source = _cfg.get('processing', 'element_source', fallback='docx_only')

    if element_source == 'hybrid':
        try:
            element_dicts = _init_reference_hybrid(dmc_string, docx_path)
        except Exception as e:
            print(f'[reference_store] Hybrid init failed ({e}), falling back to docx_only')
            from comparison_app.headless_comparator import extract_docx_elements
            elements = extract_docx_elements(docx_path)
            element_dicts = [e.to_dict() for e in elements]
    else:
        from comparison_app.headless_comparator import extract_docx_elements
        elements = extract_docx_elements(docx_path)
        element_dicts = [e.to_dict() for e in elements]

    _ensure_dir()
    now = datetime.now().isoformat(timespec='seconds')
    docx_hash = _file_hash(docx_path) if os.path.isfile(docx_path) else ''

    ref = {
        'dmc_string': dmc_string,
        'docx_hash': docx_hash,
        'created_at': now,
        'modified_at': now,
        'source': 'auto_hybrid' if element_source == 'hybrid' else 'auto',
        'elements': element_dicts,
    }

    path = _ref_path(dmc_string)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(ref, f, ensure_ascii=False, indent=2)

    return ref


def delete_reference(dmc_string: str) -> bool:
    """Delete reference for a DMC. Returns True if deleted."""
    path = _ref_path(dmc_string)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False
