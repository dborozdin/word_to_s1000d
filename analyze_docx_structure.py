#!/usr/bin/env python3
"""
Script to analyze the OOXML structure of paragraphs in РСУ_адаптированная.docx
to understand how numbered list items are stored
"""

import os
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict

def analyze_docx_paragraphs(docx_path: str):
    """
    Analyze the OOXML structure of paragraphs in a DOCX file
    """
    if not os.path.exists(docx_path):
        print(f"Document not found: {docx_path}")
        return

    # Extract document.xml from the DOCX (which is a ZIP file)
    with zipfile.ZipFile(docx_path, 'r') as zip_ref:
        # Read document.xml
        document_xml = zip_ref.read('word/document.xml')

        # Read numbering.xml if it exists
        numbering_xml = None
        try:
            numbering_xml = zip_ref.read('word/numbering.xml')
        except KeyError:
            print("No numbering.xml found")

    # Parse document.xml
    root = ET.fromstring(document_xml)

    # Namespace handling
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

    # Find all paragraphs
    paragraphs = root.findall('.//w:p', ns)

    print(f"Found {len(paragraphs)} paragraphs in document.xml")
    print("=" * 80)

    # Analyze each paragraph
    for i, para in enumerate(paragraphs):
        # Get paragraph text
        text_runs = para.findall('.//w:t', ns)
        text = ''.join([run.text for run in text_runs if run.text])

        if not text.strip():
            continue

        # Check for paragraph properties
        pPr = para.find('.//w:pPr', ns)
        style_name = "Normal"
        numPr = None
        ilvl = None
        numId = None

        if pPr is not None:
            # Check style
            pStyle = pPr.find('.//w:pStyle', ns)
            if pStyle is not None:
                style_name = pStyle.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', 'Normal')

            # Check numbering properties
            numPr = pPr.find('.//w:numPr', ns)
            if numPr is not None:
                ilvl_elem = numPr.find('.//w:ilvl', ns)
                numId_elem = numPr.find('.//w:numId', ns)

                if ilvl_elem is not None:
                    ilvl = ilvl_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')
                if numId_elem is not None:
                    numId = numId_elem.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val')

        # Look for specific text patterns
        if 'Общие сведения' in text or text.startswith('1.') or (numPr is not None):
            print(f"\nParagraph {i}:")
            print(f"  Text: '{text}'")
            print(f"  Style: {style_name}")
            print(f"  Has numbering: {numPr is not None}")
            if numPr is not None:
                print(f"  numId: {numId}")
                print(f"  ilvl: {ilvl}")

            # Show raw XML snippet for this paragraph
            print(f"  Raw XML: {ET.tostring(para, encoding='unicode')[:200]}...")

    # Analyze numbering.xml if available
    if numbering_xml:
        print("\n" + "=" * 80)
        print("NUMBERING.XML ANALYSIS")
        print("=" * 80)

        numbering_root = ET.fromstring(numbering_xml)

        # Find all abstract numbering definitions
        abstract_nums = numbering_root.findall('.//w:abstractNum', ns)
        print(f"Found {len(abstract_nums)} abstract numbering definitions")

        for i, abstract_num in enumerate(abstract_nums):
            abstract_num_id = abstract_num.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}abstractNumId')
            print(f"\nAbstract Num {abstract_num_id}:")

            # Find level definitions
            lvls = abstract_num.findall('.//w:lvl', ns)
            for lvl in lvls:
                lvl_id = lvl.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}ilvl')
                start_val = lvl.find('.//w:start', ns)
                num_fmt = lvl.find('.//w:numFmt', ns)
                lvl_text = lvl.find('.//w:lvlText', ns)

                start = start_val.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') if start_val is not None else '1'
                fmt = num_fmt.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') if num_fmt is not None else 'decimal'
                text_pattern = lvl_text.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') if lvl_text is not None else ''

                print(f"  Level {lvl_id}: start={start}, format={fmt}, pattern='{text_pattern}'")

        # Find number instances
        nums = numbering_root.findall('.//w:num', ns)
        print(f"\nFound {len(nums)} number instances:")

        for num in nums:
            num_id = num.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numId')
            abstract_num_id = num.find('.//w:abstractNumId', ns)
            abs_id = abstract_num_id.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val') if abstract_num_id is not None else 'unknown'
            print(f"  Num {num_id} -> Abstract Num {abs_id}")

if __name__ == "__main__":
    analyze_docx_paragraphs("docs/РСУ_адаптированная.docx")
