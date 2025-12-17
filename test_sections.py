#!/usr/bin/env python3
"""
Test script to debug section analysis
"""

import sys
sys.path.append('.')
from parsers.content_analyzer import analyze_document_content
from parsers.elements_analyzer import analyze_document_elements
from docx import Document

doc = Document('docs/РСУ_адаптированная.docx')
sections = analyze_document_content(doc)
elements = analyze_document_elements(doc)

print(f"Found {len(sections)} sections and {len(elements)} elements")
print()

for i, section in enumerate(sections[:3]):  # First 3 sections
    print(f'Section {i+1}: {section.get("header", "No header")}')
    print(f'  Type: {section.get("section_type")}')
    print(f'  Range: {section.get("start_para")} - {section.get("end_para")}')
    print(f'  Content lines: {len(section.get("content", []))}')

    # Find elements in this section
    start_para = section.get('start_para', 0)
    end_para = section.get('end_para', len(doc.paragraphs) - 1)
    section_elements = [elem for elem in elements if start_para <= elem.get('start_para', 0) <= end_para]

    print(f'  Elements in section: {len(section_elements)}')
    for j, elem in enumerate(section_elements[:5]):  # First 5 elements
        print(f'    Element {j+1}: {elem.get("type")} at para {elem.get("start_para")}: {elem.get("content")[:50]}...')
    print()
