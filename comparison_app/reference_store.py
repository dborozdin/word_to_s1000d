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

def _get_reference_dir() -> str:
    """Compute reference directory as {output_dir}/user_finetune/ from config.ini."""
    import configparser as _cp
    from app_paths import get_app_root, get_config_path
    _project_root = get_app_root()
    _cfg = _cp.ConfigParser()
    _cfg.read(get_config_path(), encoding='utf-8')
    _output_dir = os.path.join(_project_root,
                               _cfg.get('processing', 'output_dir', fallback='./tg_web/suites/66935'))
    return os.path.join(_output_dir, 'user_finetune')


REFERENCE_DIR = _get_reference_dir()


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


def _init_reference_xml_derived(dmc_string: str, docx_path: str, xml_path: str) -> list:
    """
    Build reference elements XML-first:
    - XML elements provide structure and types (from the generated S1000D XML)
    - stable_ids are taken from the sidecar JSON (exact match with XML renderer)
    - PDF blocks provide visual positions (bounding boxes)

    Result: reference whose element count and types exactly match the XML,
    with each element positioned in PDF space.
    """
    from comparison_app.docx_renderer import render_docx_to_pdf, is_word_available
    if not is_word_available():
        raise RuntimeError('XML-derived init requires MS Word for PDF rendering')

    pdf_path = render_docx_to_pdf(docx_path, dmc_string)

    from comparison_app.pdf_block_extractor import extract_pdf_blocks_full
    pdf_pages = extract_pdf_blocks_full(pdf_path)

    flat_blocks = []
    for page in pdf_pages:
        for block in page['blocks']:
            flat_blocks.append({**block, 'page_num': page['page_num']})

    from comparison_app.headless_comparator import extract_xml_elements
    xml_elements = extract_xml_elements(xml_path)

    # Load stable_ids in XML render order from sidecar JSON
    from comparison_app.s1000d_renderer import _load_element_map
    sidecar_map = _load_element_map(xml_path)
    stable_ids = [entry.get('stable_id', '') for entry in sidecar_map]

    from parsers.hybrid_matcher import match_xml_to_pdf
    return match_xml_to_pdf(xml_elements, flat_blocks, stable_ids)


def _init_reference_hybrid(dmc_string: str, docx_path: str) -> list:
    """Build reference elements via hybrid PDF+DOCX pipeline (with element_id)."""
    import configparser as _cp

    from app_paths import get_app_root, get_config_path
    _project_root = get_app_root()
    _cfg = _cp.ConfigParser()
    _cfg.read(get_config_path(), encoding='utf-8')
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

    from parsers.elements_analyzer import compute_stable_id

    element_dicts = []
    for ue in unified:
        text_for_id = (ue.text_start or '') + (ue.text_end or '')
        d = {
            'idx': ue.idx,
            'type': ue.type,
            'type_source': ue.type_source,
            'text_start': ue.text_start,
            'text_end': ue.text_end,
            'span': ue.span,
            'element_id': ue.element_id,
            'stable_id': compute_stable_id(ue.idx, ue.type, text_for_id),
        }
        element_dicts.append(d)

    return element_dicts


def init_reference_from_auto(dmc_string: str, docx_path: str,
                             xml_path: str = None) -> dict:
    """
    Create initial reference from automatic element extraction.

    Priority:
    1. XML-derived (xml_path provided + hybrid mode + Word available):
       XML elements → anchors; PDF blocks → positions. Best correspondence
       with the right panel since structure comes directly from generated XML.
    2. Hybrid (hybrid mode + Word available): PDF+DOCX matching.
    3. DOCX-only fallback: mammoth HTML parsing.

    Args:
        dmc_string: DMC identifier
        docx_path:  Path to the source .docx file
        xml_path:   Path to the generated S1000D XML (optional)

    Returns:
        The created reference dict.
    """
    import configparser as _cp

    from app_paths import get_config_path
    _cfg = _cp.ConfigParser()
    _cfg.read(get_config_path(), encoding='utf-8')
    element_source = _cfg.get('processing', 'element_source', fallback='docx_only')

    element_dicts = None
    source_label = 'auto'

    # Path 1: XML-derived — requires XML file + hybrid mode + MS Word
    if xml_path and os.path.isfile(xml_path) and element_source == 'hybrid':
        try:
            element_dicts = _init_reference_xml_derived(dmc_string, docx_path, xml_path)
            source_label = 'auto_xml_derived'
        except Exception as e:
            print(f'[reference_store] XML-derived init failed ({e}), trying hybrid')

    # Path 2: Hybrid PDF+DOCX — requires MS Word
    if element_dicts is None and element_source == 'hybrid':
        try:
            element_dicts = _init_reference_hybrid(dmc_string, docx_path)
            source_label = 'auto_hybrid'
        except Exception as e:
            print(f'[reference_store] Hybrid init failed ({e}), falling back to docx_only')

    # Path 3: DOCX-only fallback
    if element_dicts is None:
        from comparison_app.headless_comparator import extract_docx_elements
        from parsers.elements_analyzer import compute_stable_id
        elements = extract_docx_elements(docx_path)
        element_dicts = []
        for elem in elements:
            d = elem.to_dict()
            d['stable_id'] = compute_stable_id(
                d['idx'], d['type'], d.get('text_start', '') + d.get('text_end', '')
            )
            element_dicts.append(d)
        source_label = 'auto'

    _ensure_dir()
    now = datetime.now().isoformat(timespec='seconds')
    docx_hash = _file_hash(docx_path) if os.path.isfile(docx_path) else ''

    ref = {
        'dmc_string': dmc_string,
        'docx_hash': docx_hash,
        'created_at': now,
        'modified_at': now,
        'source': source_label,
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
