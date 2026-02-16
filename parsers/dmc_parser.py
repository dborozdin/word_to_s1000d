"""
DMC code parser for S1000D folder naming convention.
Parses folder names like: [S5-A-029-11-01-00A-028A-A] Гидрокомпенсатор. Общие данные_001_ru-RU
"""

import re
from typing import Dict, Optional, Tuple


# Regex for S1000D folder name pattern:
# [modelIdentCode-systemDiffCode-systemCode-subSystem+subSubSystem-assyCode-disassyCode+variant-infoCode+variant-itemLocationCode]
DMC_FOLDER_PATTERN = re.compile(
    r'^\[(?P<modelIdentCode>[A-Z0-9]+)-'
    r'(?P<systemDiffCode>[A-Z])-'
    r'(?P<systemCode>\d{2,3})-'
    r'(?P<subSystemCode>\d)(?P<subSubSystemCode>\d)-'
    r'(?P<assyCode>\d{2})-'
    r'(?P<disassyCode>\d{2})(?P<disassyCodeVariant>[A-Z])-'
    r'(?P<infoCode>\d{3})(?P<infoCodeVariant>[A-Z])-'
    r'(?P<itemLocationCode>[A-Z])\]\s*'
    r'(?P<titlePart>.+?)(?:_\d{3}_[a-z]{2}-[A-Z]{2})?$'
)


def parse_dmc_from_folder_name(folder_name: str) -> Optional[Dict]:
    """
    Parse DMC code components and title from S1000D-coded folder name.

    Args:
        folder_name: Folder name like '[S5-A-029-11-01-00A-028A-A] Гидрокомпенсатор. Общие данные_001_ru-RU'

    Returns:
        Dict with keys: dm_code (dict), tech_name (str), info_name (str), or None if not parseable
    """
    match = DMC_FOLDER_PATTERN.match(folder_name)
    if not match:
        return None

    dm_code = {
        'modelIdentCode': match.group('modelIdentCode'),
        'systemDiffCode': match.group('systemDiffCode'),
        'systemCode': match.group('systemCode'),
        'subSystemCode': match.group('subSystemCode'),
        'subSubSystemCode': match.group('subSubSystemCode'),
        'assyCode': match.group('assyCode'),
        'disassyCode': match.group('disassyCode'),
        'disassyCodeVariant': match.group('disassyCodeVariant'),
        'infoCode': match.group('infoCode'),
        'infoCodeVariant': match.group('infoCodeVariant'),
        'itemLocationCode': match.group('itemLocationCode'),
    }

    title_part = match.group('titlePart').strip()
    tech_name, info_name = _parse_title_parts(title_part)

    return {
        'dm_code': dm_code,
        'tech_name': tech_name,
        'info_name': info_name,
    }


def _parse_title_parts(title_text: str) -> Tuple[str, str]:
    """
    Split 'Гидрокомпенсатор. Общие данные' into (tech_name, info_name).
    Separator is '. ' (period + space).
    """
    parts = re.split(r'\.\s+', title_text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return title_text.strip(), ''


def is_descriptive_info_code(info_code: str) -> bool:
    """
    Check if info code falls in the descriptive range (000-099).
    S1000D: codes 000-099 use descript.xsd, codes >= 100 use proced.xsd.
    """
    try:
        return 0 <= int(info_code) <= 99
    except ValueError:
        return False


def build_graphic_ident_prefix(dm_code: Dict) -> str:
    """
    Build the graphic infoEntityIdent prefix from DMC code.

    Returns: e.g., 'GS5-A-029-11-01-00A-028A-A_001_RU-RU'
    """
    return (
        f"G{dm_code['modelIdentCode']}-{dm_code['systemDiffCode']}-"
        f"{dm_code['systemCode']}-{dm_code['subSystemCode']}{dm_code['subSubSystemCode']}-"
        f"{dm_code['assyCode']}-{dm_code['disassyCode']}{dm_code['disassyCodeVariant']}-"
        f"{dm_code['infoCode']}{dm_code['infoCodeVariant']}-{dm_code['itemLocationCode']}"
        f"_001_RU-RU"
    )


def dm_code_to_string(dm_code: Dict) -> str:
    """Convert DM code dict to DMC filename string."""
    return (
        f"DMC-{dm_code.get('modelIdentCode', 'S5')}-"
        f"{dm_code.get('systemDiffCode', 'A')}-"
        f"{dm_code.get('systemCode', '000')}-"
        f"{dm_code.get('subSystemCode', '0')}{dm_code.get('subSubSystemCode', '0')}-"
        f"{dm_code.get('assyCode', '00')}-"
        f"{dm_code.get('disassyCode', '00')}{dm_code.get('disassyCodeVariant', 'A')}-"
        f"{dm_code.get('infoCode', '000')}{dm_code.get('infoCodeVariant', 'A')}-"
        f"{dm_code.get('itemLocationCode', 'A')}_001"
    )
