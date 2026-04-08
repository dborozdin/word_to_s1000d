"""
Maps doc_source/ folders to their corresponding generated S1000D XML files.
Reuses parsers.dmc_parser for DMC code parsing.
"""

import os
import sys
from typing import Dict, List, Optional

# Add project root / internal root to path so we can import parsers
from app_paths import get_internal_root, long_path
sys.path.insert(0, get_internal_root())

from parsers.dmc_parser import parse_dmc_from_folder_name, dm_code_to_string


def find_docx_in_folder(folder_path: str) -> Optional[str]:
    """Find the primary .docx file at the root level of a folder."""
    skip_names = {'signaturelistved.docx'}
    for f in os.listdir(long_path(folder_path)):
        if f.startswith('~$'):
            continue
        full_path = os.path.join(folder_path, f)
        if os.path.isfile(long_path(full_path)) and f.lower().endswith('.docx') and f.lower() not in skip_names:
            return full_path
    return None


def find_doc_in_folder(folder_path: str) -> Optional[str]:
    """Find a .doc file (old Word format) at the root level of a folder."""
    for f in os.listdir(long_path(folder_path)):
        if f.startswith('~$'):
            continue
        full_path = os.path.join(folder_path, f)
        if os.path.isfile(long_path(full_path)) and f.lower().endswith('.doc') and not f.lower().endswith('.docx'):
            return full_path
    return None


def _detect_hierarchical(input_dir: str) -> bool:
    """Определяет, содержит ли input_dir двухуровневую структуру."""
    for entry in os.listdir(long_path(input_dir)):
        path = os.path.join(input_dir, entry)
        if not os.path.isdir(long_path(path)):
            continue
        # Если папка начинается с '[' — это DMC-папка, значит flat
        if entry.startswith('['):
            return False
        # Проверяем, есть ли внутри DMC-папки
        for child in os.listdir(long_path(path)):
            if child.startswith('[') and os.path.isdir(long_path(os.path.join(path, child))):
                return True
    return False


def _parse_subsystem_name(l1_folder: str) -> str:
    """Извлекает название подсистемы: '029-11-01 - Гидрокомпенсатор' → 'Гидрокомпенсатор'."""
    parts = l1_folder.split(' - ', 1)
    return parts[1].strip() if len(parts) == 2 else l1_folder


def _build_pair(entry: str, folder_path: str, output_dir: str,
                subsystem_group: str = None, subsystem_name: str = '') -> Optional[Dict]:
    """Формирует pair dict для одной DMC-папки."""
    dmc_info = parse_dmc_from_folder_name(entry)
    if dmc_info is None:
        return None

    dm_code = dmc_info['dm_code']
    dmc_string = dm_code_to_string(dm_code)
    xml_filename = f"{dmc_string}_ru-RU.xml"
    xml_path = os.path.join(output_dir, xml_filename)

    docx_path = find_docx_in_folder(folder_path)
    doc_path = None
    needs_conversion = False
    if docx_path is None:
        doc_path = find_doc_in_folder(folder_path)
        if doc_path:
            needs_conversion = True

    return {
        'folder_name': entry,
        'folder_path': folder_path,
        'docx_path': docx_path,
        'doc_path': doc_path,
        'needs_conversion': needs_conversion,
        'xml_path': xml_path,
        'docx_exists': docx_path is not None or doc_path is not None,
        'xml_exists': os.path.isfile(xml_path),
        'tech_name': dmc_info['tech_name'],
        'info_name': dmc_info['info_name'],
        'dmc_string': dmc_string,
        'info_code': dm_code['infoCode'],
        'subsystem_group': subsystem_group,
        'subsystem_name': subsystem_name,
    }


def get_comparison_pairs(input_dir: str, output_dir: str) -> List[Dict]:
    """
    Scan input_dir for DMC-coded folders and match them to generated XML files.
    Supports both flat (doc_source/) and hierarchical (subsystem/DM) structures.

    Returns list of dicts with keys:
        folder_name, folder_path, docx_path, xml_path,
        docx_exists, xml_exists, tech_name, info_name, dmc_string,
        subsystem_group, subsystem_name
    """
    pairs = []

    if not os.path.isdir(long_path(input_dir)):
        return pairs

    if _detect_hierarchical(input_dir):
        # Двухуровневая структура: L1 (подсистемы) → L2 (DMC-папки)
        for l1_entry in sorted(os.listdir(long_path(input_dir))):
            l1_path = os.path.join(input_dir, l1_entry)
            if not os.path.isdir(long_path(l1_path)):
                continue
            subsystem_name = _parse_subsystem_name(l1_entry)
            for l2_entry in sorted(os.listdir(long_path(l1_path))):
                l2_path = os.path.join(l1_path, l2_entry)
                if not os.path.isdir(long_path(l2_path)):
                    continue
                pair = _build_pair(l2_entry, l2_path, output_dir, l1_entry, subsystem_name)
                if pair:
                    pairs.append(pair)
    else:
        # Плоская структура (обратная совместимость)
        for entry in sorted(os.listdir(long_path(input_dir))):
            folder_path = os.path.join(input_dir, entry)
            if not os.path.isdir(long_path(folder_path)):
                continue
            pair = _build_pair(entry, folder_path, output_dir)
            if pair:
                pairs.append(pair)

    return pairs


def get_pair_by_dmc(dmc_string: str, input_dir: str, output_dir: str) -> Optional[Dict]:
    """Retrieve a single pair by DMC string identifier."""
    for pair in get_comparison_pairs(input_dir, output_dir):
        if pair['dmc_string'] == dmc_string:
            return pair
    return None
