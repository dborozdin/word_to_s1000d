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


def init_reference_from_auto(dmc_string: str, docx_path: str) -> dict:
    """
    Create initial reference from automatic docx element extraction.

    Args:
        dmc_string: DMC identifier
        docx_path: Path to the source .docx file

    Returns:
        The created reference dict.
    """
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
        'source': 'auto',
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
