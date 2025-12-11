"""
Text parser for docx documents.
Extracts and structures text by headings.
"""

from typing import Dict, List
from docx import Document


def extract_text_by_headings(doc: Document) -> Dict[str, str]:
    """
    Extract text content organized by heading levels.

    Args:
        doc: Docx document object

    Returns:
        Dictionary mapping heading names to their content text
    """
    sections = {}
    current_heading = None
    current_content = []

    for paragraph in doc.paragraphs:
        if paragraph.style.name.startswith('Heading'):
            # Save previous section if any
            if current_heading and current_content:
                sections[current_heading] = '\n'.join(current_content).strip()
                current_content = []

            current_heading = paragraph.text.strip()
        elif current_heading:
            # Add paragraph text to current section
            if paragraph.text.strip():  # Skip empty paragraphs
                current_content.append(paragraph.text.strip())

    # Save the last section
    if current_heading and current_content:
        sections[current_heading] = '\n'.join(current_content).strip()

    return sections


def get_document_structure(doc: Document) -> List[str]:
    """
    Get list of all headings in order.

    Args:
        doc: Docx document object

    Returns:
        List of heading texts
    """
    headings = []
    for paragraph in doc.paragraphs:
        if paragraph.style.name.startswith('Heading'):
            headings.append(paragraph.text.strip())
    return headings
