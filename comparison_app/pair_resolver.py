"""
Maps doc_source/ folders to their corresponding generated S1000D XML files.
Reuses parsers.dmc_parser for DMC code parsing.
"""

import os
import sys
from typing import Dict, List, Optional

# Add project root to path so we can import parsers
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parsers.dmc_parser import parse_dmc_from_folder_name, dm_code_to_string


def find_docx_in_folder(folder_path: str) -> Optional[str]:
    """Find the primary .docx file at the root level of a folder."""
    skip_names = {'signaturelistved.docx'}
    for f in os.listdir(folder_path):
        full_path = os.path.join(folder_path, f)
        if os.path.isfile(full_path) and f.lower().endswith('.docx') and f.lower() not in skip_names:
            return full_path
    return None


def get_comparison_pairs(input_dir: str, output_dir: str) -> List[Dict]:
    """
    Scan input_dir for DMC-coded folders and match them to generated XML files.

    Returns list of dicts with keys:
        folder_name, folder_path, docx_path, xml_path,
        docx_exists, xml_exists, tech_name, info_name, dmc_string
    """
    pairs = []

    if not os.path.isdir(input_dir):
        return pairs

    for entry in sorted(os.listdir(input_dir)):
        folder_path = os.path.join(input_dir, entry)
        if not os.path.isdir(folder_path):
            continue

        dmc_info = parse_dmc_from_folder_name(entry)
        if dmc_info is None:
            continue

        dm_code = dmc_info['dm_code']
        dmc_string = dm_code_to_string(dm_code)
        xml_filename = f"{dmc_string}_ru-RU.xml"
        xml_path = os.path.join(output_dir, xml_filename)

        docx_path = find_docx_in_folder(folder_path)

        pairs.append({
            'folder_name': entry,
            'folder_path': folder_path,
            'docx_path': docx_path,
            'xml_path': xml_path,
            'docx_exists': docx_path is not None,
            'xml_exists': os.path.isfile(xml_path),
            'tech_name': dmc_info['tech_name'],
            'info_name': dmc_info['info_name'],
            'dmc_string': dmc_string,
            'info_code': dm_code['infoCode'],
        })

    return pairs


def get_pair_by_dmc(dmc_string: str, input_dir: str, output_dir: str) -> Optional[Dict]:
    """Retrieve a single pair by DMC string identifier."""
    for pair in get_comparison_pairs(input_dir, output_dir):
        if pair['dmc_string'] == dmc_string:
            return pair
    return None
