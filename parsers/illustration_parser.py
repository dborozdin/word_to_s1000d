"""
Illustration parser for docx documents.
Extracts embedded images and tracks their references.
"""

import os
import re
from typing import Dict, List, Tuple
from docx import Document
from docx.shared import Inches
from PIL import Image as PILImage
from docx.document import Document as DocxDocument
from docx.oxml.shape import CT_Picture


def extract_illustrations(doc: Document, output_dir: str = "./tg_web/publications") -> Dict[str, str]:
    """
    Extract embedded images from document and save to output/graphics directory with S1000D naming.

    Args:
        doc: Docx document object
        output_dir: Output directory (parent of graphics subfolder)

    Returns:
        Dictionary mapping reference names to image file paths
    """
    # Create graphics subdirectory in output
    graphics_dir = os.path.join(output_dir, "graphics")
    if not os.path.exists(graphics_dir):
        os.makedirs(graphics_dir)

    illustrations = {}
    image_counter = 0  # Start from 0 for GRAPHIC0

    # Extract images from document body
    for rel in doc.part.rels.values():
        if "image" in rel.target_ref:
            # Get the image relationship
            try:
                img = rel.target_part.blob
                # Use S1000D naming convention: GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{N}.jpg
                img_name = f"GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{image_counter}.jpg"
                img_path = os.path.join(graphics_dir, img_name)

                # Save image
                with open(img_path, 'wb') as f:
                    f.write(img)

                # Map to reference number
                ref_name = f"GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{image_counter}"
                illustrations[ref_name] = img_path
                image_counter += 1

            except Exception as e:
                print(f"Error extracting image: {e}")

    return illustrations


def find_image_references(text: str) -> List[Tuple[str, str]]:
    """
    Find image references in text.

    Args:
        text: Text content to search

    Returns:
        List of (reference_type, reference_number) tuples
    """
    references = []

    # Look for figure references like "рисунок 1", "figure 1", etc.
    figure_patterns = [
        r'[Рр]ис\.\s*(\d+)',
        r'[Рр]исунок\s*(\d+)',
        r'[Фф]igure\s*(\d+)',
        r'[Ии]ллюстрация\s*(\d+)'
    ]

    for pattern in figure_patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            references.append(('figure', match))

    return references


def map_figures_to_illustrations(figure_refs: List[Tuple[str, str]], illustrations: Dict[str, str]) -> Dict[str, str]:
    """
    Map figure references to actual illustration files.

    Args:
        figure_refs: List of (type, number) references
        illustrations: Dict of illustration reference to file path

    Returns:
        Dictionary mapping figure references to illustration files
    """
    mapping = {}

    for ref_type, ref_num in figure_refs:
        # Map to S1000D GRAPHIC naming: GRAPHIC{N} where N starts from 0
        # Assume figure reference numbers are 1-indexed, convert to 0-indexed
        graphic_num = int(ref_num) - 1
        graphic_name = f"GS5-A-120-10-00-00A-041A-A_001_RU-RU-GRAPHIC{graphic_num}"

        if graphic_name in illustrations:
            mapping[f"{ref_type}_{ref_num}"] = illustrations[graphic_name]
        else:
            # Fallback: try exact mapping or other variations
            print(f"Warning: Could not find illustration for {ref_type} {ref_num}")

    return mapping


def get_document_illustrations_info(doc: Document) -> Dict[str, str]:
    """
    Get basic information about illustrations in the document.

    Args:
        doc: Docx document object

    Returns:
        Dictionary with illustration count and paths
    """
    total_images = 0

    # Count inline shapes with images
    for paragraph in doc.paragraphs:
        for run in paragraph.runs:
            if run.element.xpath('.//a:blip'):
                total_images += 1

    # Count shapes in tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        if run.element.xpath('.//a:blip'):
                            total_images += 1

    return {
        'total_count': total_images,
        'message': f'Document contains approximately {total_images} embedded images'
    }
