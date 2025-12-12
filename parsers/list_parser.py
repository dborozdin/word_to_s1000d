"""
List parser for docx documents.
Extracts numbered and bulleted lists for S1000D format.
"""

from typing import Dict, List, Optional
from docx import Document
from docx.shared import Inches


def extract_lists(doc: Document) -> List[Dict[str, str]]:
    """
    Extract lists from document.

    Args:
        doc: Docx document object

    Returns:
        List of dicts with list items and types
    """
    lists_data = []
    current_list = None
    list_items = []

    for paragraph in doc.paragraphs:
        style_name = paragraph.style.name

        # Check if paragraph is part of a list
        is_bullet = False
        is_numbered = False

        # Check if paragraph is formatted as a list in Word
        if hasattr(paragraph.paragraph_format, 'numPr') and paragraph.paragraph_format.numPr is not None:
            is_bullet = True
        else:
            # Get paragraph formatting
            text = paragraph.text.strip()
            # Check for bullet markers (simplified, including various dash characters)
            if (text.startswith('•') or text.startswith('◦') or text.startswith('-') or
                text.startswith('–') or text.startswith('—') or text.startswith('·')):
                is_bullet = True
            elif any(text.startswith(str(i) + '.') for i in range(1, 10)):
                is_numbered = True
            elif text and paragraph.paragraph_format.left_indent and paragraph.paragraph_format.left_indent > Inches(0):
                # Simple heuristic for list items with indentation
                is_bullet = True

        if is_bullet or is_numbered:
            if current_list is None or (current_list['type'] == 'bullet' and not is_bullet) or (current_list['type'] == 'numbered' and not is_numbered):
                # Save previous list
                if current_list and list_items:
                    current_list['items'] = list_items.copy()
                    lists_data.append(current_list)

                # Start new list
                list_type = 'bullet' if is_bullet else 'numbered'
                current_list = {'type': list_type, 'items': []}
                list_items = []

            # Clean text and add to current list
            clean_text = text.lstrip('•◦-–—·123456789.').strip()
            if clean_text and clean_text not in list_items:
                list_items.append(clean_text)
        else:
            # End current list if not empty
            if current_list and list_items:
                current_list['items'] = list_items.copy()
                lists_data.append(current_list)
                current_list = None
                list_items = []

    # Save final list
    if current_list and list_items:
        current_list['items'] = list_items
        lists_data.append(current_list)

    return lists_data


def convert_list_to_s1000d_randomlist(list_data: Dict[str, List[str]]) -> str:
    """
    Convert list data to S1000D randomList XML.

    Args:
        list_data: Dict with 'items' key

    Returns:
        XML string for randomList
    """
    if not list_data.get('items'):
        return ""

    items = []
    for item_text in list_data['items']:
        items.append(f"<listItem><para>{item_text}</para></listItem>")

    list_items_xml = ''.join(items)

    prefix = 'pf02' if list_data['type'] == 'bullet' else 'nfp01'

    return f'<randomList listItemPrefix="{prefix}">{list_items_xml}</randomList>'
