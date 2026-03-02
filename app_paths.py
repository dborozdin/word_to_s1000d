"""
Centralized path resolution for both normal Python and PyInstaller frozen modes.

Two root concepts:
  - APP_ROOT: directory containing the EXE (or project root in dev).
              Used for: config.ini, doc_source/, tg_web/, pdf_cache/, _overrides/
  - INTERNAL_ROOT: directory containing bundled data files (sys._MEIPASS in frozen,
              or project root in dev).
              Used for: xsd/, parsing_rules.json, comparison_app/templates/,
              comparison_app/static/, manual_data_modules/
"""

import sys
import os


def _is_frozen() -> bool:
    return getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS')


def get_app_root() -> str:
    """Directory containing the EXE (or project root in dev)."""
    if _is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_internal_root() -> str:
    """_internal directory (bundled data) or project root in dev."""
    if _is_frozen():
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_config_path() -> str:
    """Absolute path to config.ini."""
    return os.path.join(get_app_root(), 'config.ini')


def get_xsd_path(schema_name: str = 'descript.xsd') -> str:
    """Absolute path to an XSD schema file."""
    return os.path.join(get_internal_root(), 'xsd', schema_name)


def get_parsing_rules_path() -> str:
    """Absolute path to parsing_rules.json."""
    return os.path.join(get_internal_root(), 'parsing_rules.json')
